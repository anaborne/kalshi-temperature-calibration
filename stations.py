"""Step 2, propose the station mapping, print it, and stop for a human to read it.

PREREGISTRATION.md sec.4:

    Station mapping is a manual checkpoint. The pipeline parses the station
    named in each series' rules_primary and proposes an ASOS identifier.
    CLINYC -> NYC is confirmed. Every other mapping gets printed as a table and
    read by a human before the pull runs. A silently wrong station produces a
    beautiful, entirely fictional edge.

The proposal is keyed by series, not by rules text, because the rules text is
not stable: Kalshi has rewritten these contracts at least twice and the same
series names its location three different ways across its history. So the
script parses every rules_primary it has, collects the distinct location
phrases, CLI codes and settlement authorities each series has ever used, prints
them as evidence next to a single proposed station, and stops. The human
approves the series -> station claim with the evidence in front of them.

Usage:
    python stations.py             # parse, propose, verify, print, stop
    python stations.py --offline   # skip IEM verification (parse + propose only)
"""
import argparse
import collections
import datetime as dt
import hashlib
import json
import os
import re
import sys

from common import DATA, IEM, RAW, get, new_session, read_json, write_json, write_raw

MARKETS = os.path.join(DATA, "parsed", "markets.jsonl")
PROPOSAL = os.path.join(DATA, "station_proposal.json")
META_RAW = os.path.join(RAW, "iem_station_meta")
PROBE_RAW = os.path.join(RAW, "iem_probe")

PROBE_DAY = dt.date(2026, 8, 25)  # inside the settled window, for the live probe


# Three phrasings are in the wild, e.g.:
#   "...recorded at New York City (CLINYC) for Aug 25, 2026, is greater than 86..."
#   "...recorded in Central Park, New York for July 4, 2025 as reported by..."
#   "...recorded at Chicago Midway, IL for July 4, 2025, is between 88-89..."
RULE = re.compile(
    r"recorded\s+(?:at|in)\s+(?P<loc>.+?)\s*"
    r"(?:\((?P<code>CLI[A-Z]{2,5})\)\s*)?"
    r",?\s*for\s+(?P<date>[A-Z][a-z]+\.?\s+\d{1,2},\s+\d{4})",
)
AUTHORITY = [
    ("TWC", re.compile(r"The Weather Company", re.I)),
    ("NWS_CLI", re.compile(r"National Weather Service'?s Climatological Report", re.I)),
]
MONTHS = {m: i for i, m in enumerate(
    ["January", "February", "March", "April", "May", "June", "July",
     "August", "September", "October", "November", "December"], 1)}


def authority_of(rule):
    for name, pat in AUTHORITY:
        if pat.search(rule):
            return name
    return "UNKNOWN"


def parse_date(s):
    mon, day, year = re.match(r"([A-Za-z]+)\.?\s+(\d{1,2}),\s+(\d{4})", s).groups()
    for full, num in MONTHS.items():
        if full.lower().startswith(mon.lower()[:3]):
            return dt.date(int(year), num, int(day))
    return None


class Evidence:
    """Everything the rules of one series have ever said about its location."""

    def __init__(self):
        self.locs = collections.Counter()
        self.codes = collections.Counter()
        self.auth = collections.defaultdict(list)   # authority -> [date, ...]
        self.markets = 0
        self.unparsed = 0

    def add(self, loc, code, auth, date):
        self.locs[loc] += 1
        if code:
            self.codes[code] += 1
        self.auth[auth].append(date)

    def auth_spans(self):
        out = []
        for a, dates in self.auth.items():
            d = sorted(x for x in dates if x)
            out.append((a, len(dates), d[0] if d else None, d[-1] if d else None))
        return sorted(out, key=lambda r: -r[1])


def parse_rules(path):
    ev = collections.defaultdict(Evidence)
    for line in open(path, encoding="utf-8"):
        m = json.loads(line)
        e = ev[m["series_ticker"]]
        e.markets += 1
        rule = (m.get("rules_primary") or "").strip()
        hit = RULE.search(rule)
        if not hit:
            e.unparsed += 1
            continue
        loc = re.sub(r"\s+", " ", hit.group("loc")).strip(" ,")
        e.add(loc, hit.group("code"), authority_of(rule), parse_date(hit.group("date")))
    return ev


# One row per series. Every row is a claim a human has to agree with.
# `note` exists for the rows where the obvious guess is wrong.
#
#   confirmed : verified against a live market in PREREGISTRATION sec.1
#   high      : the rules name a CLI code, and the code maps to one airport
#   inferred  : the rules name only a place; the station is that place's NWS
#                CLI climate site, which is an inference, not a quotation
PROPOSALS = {
    "KXHIGHNY":    ("NYC", "confirmed", "Central Park, NOT JFK/LGA/EWR. Confirmed in sec.1."),
    "KXHIGHCHI":   ("MDW", "high", "Chicago MIDWAY. The rules never say O'Hare -- the obvious ORD guess is wrong."),
    "KXHIGHAUS":   ("AUS", "high", "Austin-Bergstrom International."),
    "KXHIGHDEN":   ("DEN", "high", "Denver International."),
    "KXHIGHLAX":   ("LAX", "high", "LA International, not downtown USC (CQT)."),
    "KXHIGHMIA":   ("MIA", "high", "Miami International."),
    "KXHIGHPHIL":  ("PHL", "high", "Philadelphia International."),
    "KXHIGHTSAN":  ("SAN", "high", "San Diego International (Lindbergh Field)."),
    "KXHIGHTATL":  ("ATL", "high", "Hartsfield-Jackson."),
    "KXHIGHTBOS":  ("BOS", "high", "Logan International."),
    "KXHIGHTDAL":  ("DFW", "high", "DFW International, NOT Love Field (DAL)."),
    "KXHIGHTDC":   ("DCA", "high", "Reagan National, NOT Dulles (IAD) or BWI."),
    # The obvious guess here is IAH and it is wrong twice over: the rules name
    # CLIHOU, and --corroborate has IAH running +0.38F ABOVE settled on 68 train
    # city-days (13/68 exact) while HOU runs -0.82F below (22/68 exact), in line
    # with every other city. An IAH mapping would have manufactured floor
    # violations out of nothing but a wrong airport.
    "KXHIGHTHOU":  ("HOU", "high", "Houston HOBBY. Rules say CLIHOU; IAH is the wrong airport."),
    "KXHIGHTLV":   ("LAS", "high", "Harry Reid International."),
    "KXHIGHTMIN":  ("MSP", "high", "Minneapolis-St Paul International."),
    "KXHIGHTNOLA": ("MSY", "high", "Louis Armstrong International."),
    "KXHIGHTOKC":  ("OKC", "high", "Will Rogers World."),
    "KXHIGHTPHX":  ("PHX", "high", "Sky Harbor International."),
    "KXHIGHTSATX": ("SAT", "high", "San Antonio International."),
    "KXHIGHTSEA":  ("SEA", "high", "Seattle-Tacoma International, NOT Boeing Field (BFI)."),
    "KXHIGHTSFO":  ("SFO", "high", "San Francisco International, not downtown."),
}

# A CLI code seen in the rules is the strongest evidence available. If a
# series' code does not match its proposal, that is a hard stop, not a warning.
CODE_TO_STATION = {
    "CLINYC": "NYC", "CLIMDW": "MDW", "CLIAUS": "AUS", "CLIDEN": "DEN",
    "CLILAX": "LAX", "CLIMIA": "MIA", "CLIPHL": "PHL", "CLISAN": "SAN",
    "CLIATL": "ATL", "CLIBOS": "BOS", "CLIDFW": "DFW", "CLIDCA": "DCA",
    "CLIHOU": "HOU", "CLILAS": "LAS", "CLIMSP": "MSP", "CLIMSY": "MSY",
    "CLIOKC": "OKC", "CLIPHX": "PHX", "CLISAT": "SAT", "CLISEA": "SEA",
    "CLISFO": "SFO",
}


def station_meta(session, station):
    """IEM's own record for this identifier. Prefers the *_ASOS network row."""
    path = os.path.join(META_RAW, f"{station}.json")
    if not os.path.exists(path):
        r = get(session, f"https://mesonet.agron.iastate.edu/api/1/station/{station}.json")
        write_raw(path, r.text)
    rows = read_json(path).get("data") or []
    asos = [r for r in rows if (r.get("network") or "").endswith("_ASOS")]
    return (asos or rows or [None])[0]


def probe_obs(session, station, tz):
    """One day of tmpf. Proves the id serves temperature and shows its precision."""
    path = os.path.join(PROBE_RAW, f"{station}.csv")
    a, b = PROBE_DAY, PROBE_DAY + dt.timedelta(days=1)
    if not os.path.exists(path):
        r = get(session, IEM, params={
            "station": station, "data": "tmpf", "format": "onlycomma",
            "report_type": ["3", "4"], "tz": tz or "UTC",
            "year1": a.year, "month1": a.month, "day1": a.day,
            "year2": b.year, "month2": b.month, "day2": b.day,
        })
        write_raw(path, r.text)
    vals, decimals = [], False
    for line in open(path, encoding="utf-8").read().splitlines()[1:]:
        parts = line.split(",")
        if len(parts) < 3:
            continue
        try:
            v = float(parts[2].strip())
        except ValueError:
            continue
        vals.append(v)
        if abs(v - round(v)) > 1e-9:
            decimals = True
    return vals, decimals


def corroborate(session, rows):
    """Compare each station's observed daily max against the settled value.

    HOLDOUT DISCIPLINE. This reads settled outcomes, so it runs on TRAIN cities
    only and refuses holdout ones outright. sec.7 says the holdout is not
    loaded, plotted or summarised until the rule is frozen, and a station check
    is not an exemption.

    This is NOT Test A. Test A (sec.5) asks whether a dominated bucket ever
    settles Yes. This asks a cruder question, whether the observed max ever
    exceeds the settled value at all, purely to catch a wrong airport. A
    station mapped to the wrong field shows up here as a positive mean
    difference or a chaotic spread, which is the failure sec.4 is guarding
    against.
    """
    settled = collections.defaultdict(dict)
    for line in open(MARKETS, encoding="utf-8"):
        m = json.loads(line)
        try:
            v = float(m.get("expiration_value"))
        except (TypeError, ValueError):
            continue
        settled[m["series_ticker"]][m["event_ticker"].rsplit("-", 1)[-1]] = v

    out = []
    for r in rows:
        if r["split"] != "train":
            continue
        stn, tz = r["proposed_station"], r["iem_tzname"]
        if not stn:
            continue
        path = os.path.join(PROBE_RAW, f"{stn}_corroborate.csv")
        if not os.path.exists(path):
            resp = get(session, IEM, params={
                "station": stn, "data": "tmpf", "format": "onlycomma",
                "report_type": ["3", "4"], "tz": tz or "UTC",
                "year1": 2026, "month1": 6, "day1": 15,
                "year2": 2026, "month2": 8, "day2": 27})
            write_raw(path, resp.text)
        daily = collections.defaultdict(list)
        for line in open(path, encoding="utf-8").read().splitlines()[1:]:
            p = line.split(",")
            if len(p) < 3:
                continue
            try:
                daily[p[1][:10]].append(float(p[2]))
            except ValueError:
                pass
        omax = {k: max(v) for k, v in daily.items()}
        diffs = [omax[event_date(ev)] - x
                 for ev, x in settled[r["series_ticker"]].items()
                 if event_date(ev) in omax]
        if not diffs:
            continue
        n = len(diffs)
        out.append({
            "series_ticker": r["series_ticker"], "station": stn, "n": n,
            "exact_pct": 100.0 * sum(1 for d in diffs if abs(d) < 1e-9) / n,
            "within_1f_pct": 100.0 * sum(1 for d in diffs if abs(d) <= 1) / n,
            "mean_diff": sum(diffs) / n,
            "obs_above_settled_pct": 100.0 * sum(1 for d in diffs if d > 0) / n,
            "worst_above": max([d for d in diffs if d > 0], default=0.0),
        })
    return out


MONTH_ABBR = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def event_date(suffix):
    """'26AUG25' -> '2026-08-25'"""
    return "20%s-%02d-%02d" % (suffix[:2], MONTH_ABBR[suffix[2:5]], int(suffix[5:]))


def split_of(series_ticker):
    """sec.7: md5(series_ticker) low bit, even to train, odd to holdout."""
    return "holdout" if int(hashlib.md5(series_ticker.encode()).hexdigest(), 16) & 1 else "train"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--offline", action="store_true", help="skip IEM verification")
    ap.add_argument("--corroborate", action="store_true",
                    help="check each TRAIN station against settled values (never holdout)")
    args = ap.parse_args()

    if not os.path.exists(MARKETS):
        sys.exit(f"missing {MARKETS} -- run fetch_markets.py first")

    ev = parse_rules(MARKETS)
    session = None if args.offline else new_session()
    universe = read_json(os.path.join(DATA, "universe.json"))
    titles = {s["series_ticker"]: s.get("title") for s in universe["series"]}

    rows = []
    for series in sorted(ev):
        e = ev[series]
        station, confidence, note = PROPOSALS.get(
            series, (None, "UNRESOLVED", "no proposal -- must be resolved by hand"))

        # A CLI code in the rules either corroborates the proposal or kills it.
        code_says = {CODE_TO_STATION.get(c, f"?{c}") for c in e.codes}
        if code_says == {station}:
            confidence = "confirmed" if confidence == "confirmed" else "code-confirmed"
        elif code_says:
            confidence = "CONFLICT"
            note = f"rules name {sorted(e.codes)} -> {sorted(code_says)}, proposal says {station}"

        meta = probe = None
        if station and not args.offline:
            meta = station_meta(session, station)
            vals, decimals = probe_obs(session, station, (meta or {}).get("tzname"))
            probe = {"n": len(vals), "max_tmpf": max(vals) if vals else None, "decimals": decimals}

        rows.append({
            "series_ticker": series,
            "title": titles.get(series),
            "settled_markets": e.markets,
            "unparsed_rules": e.unparsed,
            "rule_locations": e.locs.most_common(),
            "rule_cli_codes": e.codes.most_common(),
            "authority_spans": [
                {"authority": a, "markets": n,
                 "first": str(f) if f else None, "last": str(l) if l else None}
                for a, n, f, l in e.auth_spans()],
            "proposed_station": station,
            "confidence": confidence,
            "note": note,
            "iem_name": (meta or {}).get("name"),
            "iem_network": (meta or {}).get("network"),
            "iem_tzname": (meta or {}).get("tzname"),
            "iem_archive_begin": (meta or {}).get("archive_begin"),
            "iem_lat": (meta or {}).get("latitude"),
            "iem_lon": (meta or {}).get("longitude"),
            "probe": probe,
            "split": split_of(series),
            "approved": False,
        })

    W = 120
    print("=" * W)
    print("STATION MAPPING PROPOSAL -- read by hand before anything downstream runs")
    print("=" * W)
    print(f"{'series':<13} {'->':<2} {'stn':<4} {'confidence':<15} {'IEM name':<24} "
          f"{'network':<9} {'tz':<19} {'probe'}")
    print("-" * W)
    for r in rows:
        p = r["probe"]
        ptxt = "-" if not p else f"n={p['n']:<3} max={p['max_tmpf']}{'  DECIMAL' if p['decimals'] else ''}"
        print(f"{r['series_ticker']:<13} {'->':<2} {str(r['proposed_station']):<4} "
              f"{r['confidence']:<15} {str(r['iem_name'])[:24]:<24} "
              f"{str(r['iem_network']):<9} {str(r['iem_tzname']):<19} {ptxt}")
    print("-" * W)

    print("\nEVIDENCE -- every location phrase and CLI code these rules have ever used")
    for r in rows:
        locs = ", ".join(f"{l!r}x{c}" for l, c in r["rule_locations"][:4])
        codes = ", ".join(f"{c}x{n}" for c, n in r["rule_cli_codes"]) or "(none)"
        print(f"  {r['series_ticker']:<13} -> {r['proposed_station']}   codes: {codes}")
        print(f"  {'':<13}    says: {locs}")
        print(f"  {'':<13}    note: {r['note']}")

    print("\nSETTLEMENT AUTHORITY, AND WHEN IT CHANGED")
    for r in rows:
        spans = "  ".join(f"{s['authority']}({s['markets']}) {s['first']}..{s['last']}"
                          for s in r["authority_spans"])
        print(f"  {r['series_ticker']:<13} {spans}")
    mixed = [r for r in rows if len(r["authority_spans"]) > 1]
    if mixed:
        print(f"\n  !! {len(mixed)}/{len(rows)} series changed settlement authority partway through.")
        print("     PREREGISTRATION sec.1 resolved TWC-vs-NWS by reading a live Aug 2026 market.")
        print("     That reading is correct for the current era and does NOT hold for the whole")
        print("     settled sample: older markets in the same series settle on the NWS")
        print("     Climatological Report. Test A would pool two settlement regimes.")
        print("     This is a human decision and it has to be made before step 3.")

    print("\nRULE-PARSE HEALTH")
    tot_bad = sum(r["unparsed_rules"] for r in rows)
    print(f"  {len(rows)} series, {sum(r['settled_markets'] for r in rows):,} markets, "
          f"{tot_bad} rules_primary strings unparsed")
    for r in rows:
        if r["unparsed_rules"]:
            print(f"  !! {r['series_ticker']}: {r['unparsed_rules']}/{r['settled_markets']} unparsed")
    bad = [r for r in rows if r["confidence"] in ("CONFLICT", "UNRESOLVED")]
    for r in bad:
        print(f"  !! {r['series_ticker']}: {r['confidence']} -- {r['note']}")

    corr = []
    if args.corroborate and not args.offline:
        corr = corroborate(session, rows)
        print("\nCORROBORATION -- observed daily max vs settled value, TRAIN CITIES ONLY")
        print("  (not Test A; a crude wrong-airport check. sec.7 keeps holdout out of it.)")
        print(f"  {'series':<13} {'stn':<4} {'n':>4} {'exact':>6} {'<=1F':>6} "
              f"{'meanDiff':>9} {'obs>settled':>12} {'worst+':>7}")
        for c in corr:
            print(f"  {c['series_ticker']:<13} {c['station']:<4} {c['n']:>4} "
                  f"{c['exact_pct']:>5.0f}% {c['within_1f_pct']:>5.0f}% {c['mean_diff']:>9.2f} "
                  f"{c['obs_above_settled_pct']:>11.0f}% {c['worst_above']:>7.1f}")
        bad = [c for c in corr if c["mean_diff"] > 0 or c["obs_above_settled_pct"] > 20]
        for c in bad:
            print(f"  !! {c['series_ticker']} looks like the wrong field -- "
                  f"mean {c['mean_diff']:+.2f}F, {c['obs_above_settled_pct']:.0f}% above settled")
        if not bad:
            print("  all train stations sit below settled with a consistent negative offset")

    print("\nTRAIN / HOLDOUT SPLIT  (sec.7: md5(series_ticker) low bit, even=train odd=holdout)")
    for which in ("train", "holdout"):
        who = [r for r in rows if r["split"] == which]
        print(f"  {which:<8} {len(who):>2} cities, ~{sum(r['settled_markets'] for r in who)/6:,.0f} "
              f"city-days: {' '.join(r['series_ticker'] for r in who)}")
    tr = sum(r["settled_markets"] for r in rows if r["split"] == "train")
    ho = sum(r["settled_markets"] for r in rows if r["split"] == "holdout")
    if tr + ho:
        print(f"  by city-day count: {100*tr/(tr+ho):.0f}/{100*ho/(tr+ho):.0f} train/holdout")
        print("  sec.7: take this as printed. Reseeding to taste is holdout leakage in a lab coat.")

    write_json(PROPOSAL, {"probe_day": str(PROBE_DAY), "approved": False,
                          "rows": rows, "corroboration_train_only": corr})

    print("\n" + "=" * W)
    print(f"WROTE {PROPOSAL}")
    print("STOPPING HERE, as sec.4 requires. Nothing downstream runs until a human has read")
    print('the table above, corrected any row, and set "approved": true in that file.')
    print("=" * W)


if __name__ == "__main__":
    main()
