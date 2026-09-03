"""Step 3, bulk-pull hourly observations for every approved station.

PREREGISTRATION.md sec.3: Iowa Environmental Mesonet ASOS archive, unauthenticated
CSV, `report_type=3,4` so that a spike appearing only in a SPECI still counts
toward the day's maximum, `tz` set to the city's local timezone so that "the
day" means the local calendar day the contract settles on.

Depth. The archive starts at the ASOS deployment boundary, see ARCHIVE_START.
sec.6's table is fit on observations alone, so the market sample's date range
does not bind here. Correction 2 fixes the far end of the FIT window, and
Correction 4 moves that cutoff to 2021-08-01; the pull itself still runs to the
end of the settled market window, because check_depth_bias.py reads the later
years.

Raw per-year responses land under data/raw/obs/<station>/<year>.csv and are
concatenated into one CSV per station at data/obs/<station>.csv. Chunking by
year is what makes the pull resumable; a single 16-year request that dies at
minute nine leaves nothing behind.

Gated on data/station_proposal.json approved:true, per sec.4.

Usage:
    python fetch_obs.py                  # resumable
    python fetch_obs.py --from 2005      # deeper archive
    python fetch_obs.py --station NYC    # one station
"""
import argparse
import collections
import datetime as dt
import os
import sys

from common import DATA, IEM, RAW, ensure, get, new_session, read_json, write_raw, short

PROPOSAL = os.path.join(DATA, "station_proposal.json")
OBS_RAW = os.path.join(RAW, "obs")
OBS = os.path.join(DATA, "obs")

# The ASOS deployment boundary. The Automated Surface Observing System was
# commissioned across the US network through the mid-1990s, and it is the
# measurement process that produces the observations this study trades
# against today. Data from 1995 forward is the same instrument, the same
# automated reporting cadence and the same siting regime as the current feed;
# data before it is a different process, largely manual observation, that
# happens to report the same units.
#
# So the boundary is chosen for measurement-process continuity, not for sample
# size. It is deliberately NOT justified by Correction 2's "roughly 900
# observations per cell": that figure was illustrative arithmetic in prose, and
# setting a pipeline parameter to reproduce a number from prose is
# reverse-justification, dressing a free choice as a finding.
#
# check_depth_bias.py measures what the choice costs: NYC carries a real
# reporting-density step change, 26.1 -> 30.7 obs/day across the 1995-2009 /
# 2010-2024 boundary, worth +0.122F of mean residual at H=13, which is
# statistically clear and economically negligible at -0.013c of signed fair
# value against a 10c entry threshold. An earlier version of this comment put
# the pair at "24 -> ~30 obs/day at 2005"; the eras are fixed at 1995-2009 and
# 2010-2024, so nothing here measures a break at 2005.
# A 2005 start would halve that shift, and was rejected: picking a cutoff
# because it improves a diagnostic is selecting a nuisance parameter on that
# diagnostic, which is the tuning pattern sec.6 exists to prevent.
ARCHIVE_START = 1995
ARCHIVE_END = dt.date(2026, 8, 27)  # end of the settled market window, inclusive

HEADER = "station,valid,tmpf"


def approved_stations():
    if not os.path.exists(PROPOSAL):
        sys.exit(f"missing {PROPOSAL} -- run stations.py first")
    prop = read_json(PROPOSAL)
    if not prop.get("approved"):
        sys.exit("data/station_proposal.json is not approved -- sec.4 requires a "
                 "human to read the mapping table before this pull runs")
    out = []
    for r in prop["rows"]:
        if not r.get("proposed_station"):
            sys.exit(f"{r['series_ticker']} has no station -- resolve it before pulling")
        out.append((r["series_ticker"], r["proposed_station"], r["iem_tzname"]))
    return out


def pull_year(session, station, tz, year):
    """One calendar year of tmpf for one station, in that city's local time."""
    path = os.path.join(OBS_RAW, station, f"{year}.csv")
    if os.path.exists(path):
        return path, True
    a = dt.date(year, 1, 1)
    b = min(dt.date(year + 1, 1, 1), ARCHIVE_END + dt.timedelta(days=1))
    r = get(session, IEM, params={
        "station": station, "data": "tmpf", "format": "onlycomma",
        "report_type": ["3", "4"], "tz": tz,
        "year1": a.year, "month1": a.month, "day1": a.day,
        "year2": b.year, "month2": b.month, "day2": b.day,
    }, timeout=300)
    write_raw(path, r.text)
    return path, False


def concat(station):
    """Stitch the per-year raw files into one CSV, header once, sorted by time."""
    src = os.path.join(OBS_RAW, station)
    rows = []
    for name in sorted(os.listdir(src)):
        if not name.endswith(".csv"):
            continue
        for line in open(os.path.join(src, name), encoding="utf-8").read().splitlines():
            line = line.strip()
            if not line or line.startswith("station,") or line.startswith("#"):
                continue
            rows.append(line)
    rows.sort(key=lambda r: r.split(",", 2)[1] if r.count(",") >= 2 else r)
    out = os.path.join(OBS, f"{station}.csv")
    ensure(OBS)
    with open(out, "w", encoding="utf-8") as f:
        f.write(HEADER + "\n")
        f.write("\n".join(rows) + "\n")
    return out, len(rows)


def summarise(path):
    """Row count, span, usable-value count, and whether values carry decimals."""
    n = usable = 0
    first = last = None
    decimals = False
    years = collections.Counter()
    for line in open(path, encoding="utf-8"):
        if line.startswith("station,"):
            continue
        p = line.rstrip("\n").split(",")
        if len(p) < 3:
            continue
        n += 1
        stamp = p[1]
        first = first or stamp
        last = stamp
        years[stamp[:4]] += 1
        try:
            v = float(p[2])
        except ValueError:
            continue
        usable += 1
        if abs(v - round(v)) > 1e-9:
            decimals = True
    return n, usable, first, last, decimals, years


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", type=int, default=ARCHIVE_START)
    ap.add_argument("--station", help="pull one station only")
    ap.add_argument("--summary", action="store_true",
                    help="re-report the per-station table and the totals from "
                         "the existing cache, pulling nothing")
    args = ap.parse_args()

    stations = approved_stations()
    if args.station:
        stations = [s for s in stations if s[1] == args.station]
        if not stations:
            sys.exit(f"{args.station} is not in the approved mapping")

    session = None if args.summary else new_session()
    years = list(range(args.start, ARCHIVE_END.year + 1))
    kind = "cache summary" if args.summary else "observation pull"
    print(f"== {kind}: {len(stations)} stations x {len(years)} years "
          f"({args.start}-{ARCHIVE_END.year}) ==")

    tot_rows = tot_usable = 0
    for i, (series, station, tz) in enumerate(stations, 1):
        fetched = 0
        if not args.summary:
            for y in years:
                _, cached = pull_year(session, station, tz, y)
                fetched += 0 if cached else 1
        path, _ = concat(station)
        n, usable, first, last, decimals, byyear = summarise(path)
        tot_rows += n
        tot_usable += usable
        thin = [y for y in years if byyear.get(str(y), 0) < 2000]
        print(f"  [{i:>2}/{len(stations)}] {station:<4} {series:<13} {n:>8,} rows "
              f"{usable:>8,} usable  {str(first)[:10]}..{str(last)[:10]}  "
              f"{'decimal' if decimals else 'whole-F'}  "
              f"{fetched} pulled{'  THIN:' + ','.join(map(str, thin)) if thin else ''}")
        sys.stdout.flush()

    # Reconciliation: the totals a downstream document quotes should be
    # printed by the step that produced them, not summed by hand out of a
    # per-station table.
    print(f"\n  TOTAL {len(stations)} stations  {tot_rows:,} rows  "
          f"{tot_usable:,} usable  ({tot_rows - tot_usable:,} dropped: "
          f"non-numeric tmpf, mostly 'M' for missing)")
    print(f"  one CSV per station under {short(OBS)}/")


if __name__ == "__main__":
    main()
