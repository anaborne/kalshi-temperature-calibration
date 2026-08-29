"""Step 5, Test A, the safety test. Section 5, as amended by Checkpoint 1 and Correction 1.

Two statistics, in the order Checkpoint 1 fixed:

  PRIMARY    D = expiration_value - (final observed max), per city-day, as a
             distribution per stratum. D > 0 is the safe direction: settlement
             reading above observation keeps the floor intact.

             Correction 1: expiration_value is populated on recent markets and
             empty across much of 2021-2024 and Nov-Dec 2025. Where it is
             missing, sec.2's bucket recovery takes over. That does not yield a
             number, so it is reported as what it actually is, a three-way
             classification of D's SIGN:

               D > 0 certain    winning bucket lies entirely above observed max
               indeterminate    winning bucket contains observed max (pays nothing
                                either way, which is sec.2's whole argument)
               D < 0 certain    winning bucket lies entirely below observed max,
                                a floor violation, and the same event the
                                secondary statistic counts at H=23

  MARGIN     A violation count of zero is not a headline on its own. For every
             city-day, how many further degrees of negative D would have been
             required to flip a dominated bucket, meaning to push the settled
             value down into a bucket lying entirely below the observed max.
             Margin 0 means the day IS a violation; margin 1 means it was one
             degree away. A zero-violation record where the mass sits at 1-2
             degrees is fragile and a bound computed from it is close to
             meaningless; one where the mass sits at 3+ is genuinely robust.
             Distribution reported per stratum alongside the violation count.

  SECONDARY  sec.5's dominated-bucket violations. For each city-day and each
             local hour H in 09:00..23:00, M_H is the max tmpf observed from
             00:00 local through H. A bucket is dominated at H when its entire
             range lies strictly below M_H, and a dominated bucket that settles
             Yes is a violation.

STRATIFICATION, over two dimensions, and neither may be pooled away.

  Authority (Checkpoint 1). 20 of 21 series switched from the NWS Climatological
  Report to The Weather Company on ~2026-08-14. The NWS report derives from the
  same ASOS observations IEM serves, so a clean NWS result is reassuring for the
  wrong reason. Every market from mid-August forward settles on TWC. The TWC
  stratum is the only one that speaks to the forward regime and it is the small
  one, and Correction 1 is explicit that the deep archive does not enlarge it.

  Season (Correction 1). The premise of C3, that by late afternoon the day's
  maximum is substantially determined, is a summer fact. In winter the maximum
  frequently lands at an odd hour on a warm front, the sec.5 floor still holds,
  and the sec.6 residual distribution widens and shifts. A pooled figure would
  average two different games and describe neither.

  The pooled row is printed last, labelled, and is not the headline.

CLUSTERING. 21 cities on one calendar day share a synoptic regime and share
whatever the settlement methodology does that day. They are not 21 independent
observations. Rule-of-three bounds are computed on distinct dates. The
triple-level bound is printed alongside, labelled as the overstatement it is.

INTEGER SETTLEMENT. Every populated expiration_value in the sample is a whole
degree, so a "less than 101" market's yes-set has supremum 100, not 101.
Domination is evaluated against the attainable set, which declares domination
slightly more often than a continuous reading and makes the test stricter.

Test A runs on all 21 cities. sec.7's embargo governs the Test B rule; Test A is
the gate deciding whether Test B is worth running at all.
"""
import argparse
import collections
import datetime as dt
import json
import math
import os
import re
import sys

from buckets import bounds_text, in_bucket, yes_bounds
from common import DATA, read_json, write_json, short

MARKETS = os.path.join(DATA, "parsed", "markets.jsonl")
PROPOSAL = os.path.join(DATA, "station_proposal.json")
OBS = os.path.join(DATA, "obs")
RESULTS = os.path.join(DATA, "test_a_results.json")

HOURS = range(9, 24)
MONTH_ABBR = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}
SEASONS = {12: "winter", 1: "winter", 2: "winter",
           3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer",
           9: "autumn", 10: "autumn", 11: "autumn"}
SEASON_ORDER = ["winter", "spring", "summer", "autumn"]
AUTHORITIES = ["TWC", "NWS_CLI", "UNSPECIFIED"]

# Three wordings of the same NWS product appear across the sample --
# "Climatological Report", "Daily Climate Report", "NWS's Daily Climate Report".
# CLI is the Climatological Report (Daily); the Daily Climate Report is the same
# product under its common name, so they form one stratum. The wording
# breakdown is printed anyway rather than asserted away.
AUTHORITY_PATTERNS = [
    ("TWC", re.compile(r"The Weather Company", re.I)),
    ("NWS_CLI", re.compile(
        r"(National Weather Service'?s|NWS'?s?)\s+(Daily\s+Climate|Climatological)\s+Report",
        re.I)),
]
NWS_WORDING = AUTHORITY_PATTERNS[1][1]


def authority_of(rule):
    """TWC, NWS_CLI, or UNSPECIFIED. The oldest markets name no source at all."""
    for name, pat in AUTHORITY_PATTERNS:
        if pat.search(rule or ""):
            return name
    return "UNSPECIFIED"


def nws_wording(rule):
    m = NWS_WORDING.search(rule or "")
    return m.group(0) if m else None


def event_date(event_ticker):
    s = event_ticker.rsplit("-", 1)[-1]
    try:
        return dt.date(2000 + int(s[:2]), MONTH_ABBR[s[2:5]], int(s[5:]))
    except (ValueError, KeyError, IndexError):
        return None


def round_half_up(x):
    return math.floor(x + 0.5)


def violation_margin(markets, settled, observed_max):
    """Degrees of additional negative D needed to make this day a violation.

    A violation exists exactly when the bucket containing the settled value lies
    entirely below the observed max. The binding hour is H=23, where M_H is the
    full-day max. So walk the settled value downward one whole degree at a time
    and stop at the first value whose containing bucket has an upper bound below
    the observed max. 0 means the day already is a violation. None means no
    reachable bucket would do it, which happens when the ladder does not extend
    far enough below the observation.
    """
    if settled is None:
        return None
    for delta in range(0, 41):
        v = settled - delta
        for m in markets:
            lo, hi = yes_bounds(m)
            if lo is not None and v < lo:
                continue
            if hi is not None and v > hi:
                continue
            if hi is not None and hi < observed_max:
                return delta
            break                      # the containing bucket is not below the max
    return None


def quantile(vals, q):
    if not vals:
        return None
    i = q * (len(vals) - 1)
    lo, hi = math.floor(i), math.ceil(i)
    return vals[int(i)] if lo == hi else vals[lo] + (vals[hi] - vals[lo]) * (i - lo)


def load_ladders():
    by = collections.defaultdict(list)
    for line in open(MARKETS, encoding="utf-8"):
        m = json.loads(line)
        by[m["event_ticker"]].append(m)
    out = {}
    for ev, ms in by.items():
        date = event_date(ev)
        if date is None:
            continue
        auths = {authority_of(m.get("rules_primary")) for m in ms}
        winners = [m for m in ms if m.get("result") == "yes"]
        val = None
        for m in ms:
            try:
                val = float(m.get("expiration_value"))
                break
            except (TypeError, ValueError):
                continue
        out[ev] = {
            "event_ticker": ev, "series_ticker": ms[0]["series_ticker"],
            "date": date, "season": SEASONS[date.month],
            "authority": auths.pop() if len(auths) == 1 else "MIXED",
            "tier": ms[0].get("tier", "live"), "markets": ms,
            "settled_value": val, "n_markets": len(ms),
            "winner": winners[0] if len(winners) == 1 else None,
            "n_winners": len(winners),
        }
    return out


def load_obs(station):
    path = os.path.join(OBS, f"{station}.csv")
    if not os.path.exists(path):
        return None
    days = collections.defaultdict(list)
    for line in open(path, encoding="utf-8"):
        if line.startswith("station,"):
            continue
        p = line.rstrip("\n").split(",")
        if len(p) < 3:
            continue
        try:
            v = float(p[2])
        except ValueError:
            continue
        days[p[1][:10]].append((int(p[1][11:13]), v))
    return days


def day_profile(obs_day, rounded):
    if not obs_day:
        return None, None
    vals = [(h, round_half_up(v) if rounded else v) for h, v in obs_day]
    by_hour = collections.defaultdict(list)
    for h, v in vals:
        by_hour[h].append(v)
    m_h, running = {}, None
    for h in range(24):
        for v in by_hour.get(h, ()):
            if running is None or v > running:
                running = v
        if h in HOURS:
            m_h[h] = running
    return m_h, max(v for _, v in vals)


def run(ladders, obs_by_station, station_of, rounded):
    days, dom_rows, violations, skipped = [], [], [], collections.Counter()

    for ev, lad in sorted(ladders.items()):
        station = station_of.get(lad["series_ticker"])
        obs = obs_by_station.get(station)
        if obs is None:
            skipped["no observation file"] += 1
            continue
        obs_day = obs.get(lad["date"].isoformat())
        if not obs_day:
            skipped["no observations that day"] += 1
            continue
        m_h, final = day_profile(obs_day, rounded)

        # Primary: D, exact where the field exists, sign-classified where not.
        rec = {"event_ticker": ev, "series_ticker": lad["series_ticker"],
               "date": lad["date"].isoformat(), "season": lad["season"],
               "authority": lad["authority"], "tier": lad["tier"],
               "n_markets": lad["n_markets"], "observed_max": final,
               "settled": lad["settled_value"], "D": None, "sign": None,
               "margin": violation_margin(lad["markets"], lad["settled_value"], final)}
        if lad["settled_value"] is not None:
            rec["D"] = lad["settled_value"] - final
            rec["sign"] = ("D<0" if rec["D"] < 0 else "D>0" if rec["D"] > 0 else "D=0")
            rec["basis"] = "expiration_value"
        elif lad["winner"] is not None:
            lo, hi = yes_bounds(lad["winner"])
            rec["winning_bucket"] = bounds_text((lo, hi))
            if lo is not None and lo > final:
                rec["sign"], rec["basis"] = "D>0", "bucket recovery"
            elif hi is not None and hi < final:
                rec["sign"], rec["basis"] = "D<0", "bucket recovery"
            else:
                rec["sign"], rec["basis"] = "indeterminate", "bucket recovery"
        else:
            skipped["no settled value and no single winner"] += 1
            continue
        days.append(rec)

        # Secondary: dominated buckets that settled Yes.
        for H in HOURS:
            M = m_h.get(H)
            if M is None:
                continue
            for m in lad["markets"]:
                _, hi = yes_bounds(m)
                if hi is None or not hi < M:
                    continue
                dom_rows.append((lad["date"].isoformat(), lad["authority"], lad["season"]))
                if m.get("result") == "yes":
                    violations.append({
                        "event_ticker": ev, "series_ticker": lad["series_ticker"],
                        "date": lad["date"].isoformat(), "season": lad["season"],
                        "authority": lad["authority"], "hour": H,
                        "bucket": m["ticker"].rsplit("-", 1)[-1],
                        "bucket_range": bounds_text(yes_bounds(m)), "M_H": M,
                        "observed_max": final, "settled_value": lad["settled_value"],
                        "settled_bucket": (bounds_text(yes_bounds(lad["winner"]))
                                           if lad["winner"] else None),
                    })
    return days, dom_rows, violations, skipped


def summarise_d(rows):
    """Full distribution, not mean and min. All of the risk is in the left tail."""
    exact = sorted(r["D"] for r in rows if r["D"] is not None)
    signs = collections.Counter(r["sign"] for r in rows)
    out = {"n_city_days": len(rows), "n_dates": len({r["date"] for r in rows}),
           "n_exact": len(exact), "signs": dict(signs),
           "n_D_negative": signs.get("D<0", 0),
           "n_indeterminate": signs.get("indeterminate", 0)}
    if exact:
        mean = sum(exact) / len(exact)
        var = sum((v - mean) ** 2 for v in exact) / (len(exact) - 1) if len(exact) > 1 else 0.0
        out.update({"mean": mean, "sd": math.sqrt(var),
                    "min": exact[0], "max": exact[-1],
                    "p01": quantile(exact, .01), "p05": quantile(exact, .05),
                    "p25": quantile(exact, .25), "p50": quantile(exact, .50),
                    "p75": quantile(exact, .75), "p95": quantile(exact, .95),
                    "p99": quantile(exact, .99),
                    "pct_negative_of_exact": 100.0 * sum(1 for v in exact if v < 0) / len(exact),
                    "left_tail_counts": dict(collections.Counter(
                        v for v in exact if v <= 0))})
    margins = sorted(r["margin"] for r in rows if r["margin"] is not None)
    out["margin"] = margin_summary(margins, len(rows))
    return out


def margin_summary(margins, n_rows):
    if not margins:
        return {"n": 0}
    hist = collections.Counter(margins)
    n = len(margins)
    return {"n": n, "unreachable": n_rows - n,
            "min": margins[0], "p01": quantile(margins, .01),
            "p05": quantile(margins, .05), "p25": quantile(margins, .25),
            "p50": quantile(margins, .50), "max": margins[-1],
            "at_0": hist.get(0, 0), "at_1": hist.get(1, 0), "at_2": hist.get(2, 0),
            "le_1_pct": 100.0 * sum(1 for m in margins if m <= 1) / n,
            "le_2_pct": 100.0 * sum(1 for m in margins if m <= 2) / n,
            "ge_3_pct": 100.0 * sum(1 for m in margins if m >= 3) / n,
            "histogram": dict(sorted(hist.items()))}


def summarise_dom(dom_rows, violations):
    """Counts at three units, plus a date-clustered CI when the floor leaks.

    A raw violation count over (city-day, bucket, H) triples overstates what
    happened: one bad city-day reappears at every hour of the afternoon, so a
    single divergence can show up thirteen times. City-days and dates are the
    units that correspond to independent events.
    """
    n = len(dom_rows)
    k = len({d for d, _, _ in dom_rows})
    vdates = {v["date"] for v in violations}
    vdays = {v["event_ticker"] for v in violations}
    out = {"n_dominated_bucket_hours": n, "n_dates": k,
           "n_violations": len(violations),
           "n_violating_city_days": len(vdays), "n_violating_dates": len(vdates),
           "violation_rate_pct": (100.0 * len(violations) / n) if n else None,
           "date_violation_rate_pct": (100.0 * len(vdates) / k) if k else None,
           "rule_of_three_by_date": (3.0 / k) if k and not violations else None,
           "rule_of_three_by_triple": (3.0 / n) if n and not violations else None}
    if violations and n:
        lo, hi = date_clustered_rate_ci(dom_rows, violations)
        out["rate_ci95_lo_pct"], out["rate_ci95_hi_pct"] = lo, hi
    return out


def date_clustered_rate_ci(dom_rows, violations, reps=4000):
    """95% percentile bootstrap on the violation rate, resampling whole DATES.

    Checkpoint 1: 21 cities on one calendar day are not 21 independent
    observations. Resampling triples would give a spuriously tight interval and
    the sec.5 kill threshold is close enough to the measured rate that the width
    decides the verdict.
    """
    import random
    per_date_dom = collections.Counter(d for d, _, _ in dom_rows)
    per_date_vio = collections.Counter(v["date"] for v in violations)
    dates = sorted(per_date_dom)
    rng = random.Random(20260827)
    rates = []
    for _ in range(reps):
        dom = vio = 0
        for _ in range(len(dates)):
            d = dates[rng.randrange(len(dates))]
            dom += per_date_dom[d]
            vio += per_date_vio.get(d, 0)
        if dom:
            rates.append(100.0 * vio / dom)
    if not rates:
        return None, None
    rates.sort()
    return rates[int(0.025 * len(rates))], rates[int(0.975 * len(rates))]


def verdict(rate, n):
    if rate is None:
        return "no data"
    if rate == 0:
        return f"clean ({n:,} dominated-bucket-hours)"
    if rate < 0.5:
        return f"FLOOR LEAKS at {rate:.4f}% -- price the leak into every trade"
    return f"C3 DIES: {rate:.4f}% >= 0.5%"


def strata_of(days, dom_rows, violations):
    """(label, day rows, dominated rows, violations) for every reported stratum."""
    out = []
    for auth in AUTHORITIES:
        out.append((auth,
                    [r for r in days if r["authority"] == auth],
                    [x for x in dom_rows if x[1] == auth],
                    [v for v in violations if v["authority"] == auth]))
        for season in SEASON_ORDER:
            d = [r for r in days if r["authority"] == auth and r["season"] == season]
            if not d:
                continue
            out.append((f"  {auth}/{season}", d,
                        [x for x in dom_rows if x[1] == auth and x[2] == season],
                        [v for v in violations if v["authority"] == auth
                         and v["season"] == season]))
    out.append(("POOLED", days, dom_rows, violations))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-print", type=int, default=120)
    args = ap.parse_args()

    prop = read_json(PROPOSAL)
    if not prop.get("approved"):
        sys.exit("station mapping not approved -- sec.4")
    station_of = {r["series_ticker"]: r["proposed_station"] for r in prop["rows"]}

    ladders = load_ladders()
    obs_by_station = {s: load_obs(s) for s in sorted(set(station_of.values()))}
    missing = [s for s, v in obs_by_station.items() if v is None]
    if missing:
        sys.exit(f"missing observation files for {missing} -- run fetch_obs.py")

    tiers = collections.Counter(l["tier"] for l in ladders.values())
    dates = {l["date"] for l in ladders.values()}
    print("=" * 108)
    print("TEST A -- the safety test (sec.5; Checkpoint 1 and Correction 1 amendments applied)")
    print("=" * 108)
    print(f"  {len(ladders):,} settled city-days, {len(station_of)} cities, "
          f"{len(dates)} distinct dates, {min(dates)} .. {max(dates)}")
    print(f"  tiers: {dict(tiers)}")
    print(f"  by season: {dict(collections.Counter(l['season'] for l in ladders.values()))}")
    print(f"  by authority: {dict(collections.Counter(l['authority'] for l in ladders.values()))}")
    wording = collections.Counter()
    span = {}
    for l in ladders.values():
        w = nws_wording(l["markets"][0].get("rules_primary"))
        if w:
            wording[w] += 1
            lo, hi = span.get(w, (l["date"], l["date"]))
            span[w] = (min(lo, l["date"]), max(hi, l["date"]))
    if wording:
        print("  NWS_CLI pools three wordings of the same product:")
        for w, n in wording.most_common():
            print(f"    {n:>6,} city-days  {span[w][0]} .. {span[w][1]}  {w!r}")
    n_unspec = sum(1 for l in ladders.values() if l["authority"] == "UNSPECIFIED")
    if n_unspec:
        ds = [l["date"] for l in ladders.values() if l["authority"] == "UNSPECIFIED"]
        print(f"  UNSPECIFIED: {n_unspec:,} city-days ({100*n_unspec/len(ladders):.1f}%), "
              f"{min(ds)} .. {max(ds)} -- rules name no settlement source at all.")
        print(f"    Kept as its own stratum rather than folded into NWS. Assuming an")
        print(f"    unstated source is the same as a stated one is the error sec.1 made.")

    results = {}
    for rounded in (False, True):
        variant = "rounded" if rounded else "unrounded"
        days, dom_rows, violations, skipped = run(ladders, obs_by_station, station_of, rounded)
        strata = strata_of(days, dom_rows, violations)
        results[variant] = {"skipped": dict(skipped), "strata": {}}

        print(f"\n{'=' * 108}\nVARIANT: {variant.upper()}  "
              f"(observations {'rounded half-up to whole degrees' if rounded else 'as reported'})")
        if skipped:
            print(f"  city-days skipped: {dict(skipped)}")

        print(f"\n  PRIMARY -- D = settled value minus final observed max, degrees F")
        print(f"  Full distribution. Summary stats hide the shape of the left tail and")
        print(f"  every dollar of this strategy's risk lives there.")
        print(f"  {'stratum':<18} {'days':>7} {'dates':>6} {'exact':>7} {'mean':>6} {'sd':>5} "
              f"{'min':>5} {'p01':>5} {'p05':>5} {'p25':>5} {'p50':>5} {'p75':>5} {'p95':>5} "
              f"{'p99':>5} {'max':>5} {'D<0':>5} {'indet':>6}")
        for label, d, _, _ in strata:
            st = summarise_d(d)
            tag = "  <- not the headline" if label == "POOLED" else ""
            if "mean" in st:
                print(f"  {label:<18} {st['n_city_days']:>7,} {st['n_dates']:>6,} "
                      f"{st['n_exact']:>7,} {st['mean']:>6.2f} {st['sd']:>5.2f} "
                      f"{st['min']:>5.1f} {st['p01']:>5.1f} {st['p05']:>5.1f} {st['p25']:>5.1f} "
                      f"{st['p50']:>5.1f} {st['p75']:>5.1f} {st['p95']:>5.1f} {st['p99']:>5.1f} "
                      f"{st['max']:>5.1f} {st['n_D_negative']:>5,} {st['n_indeterminate']:>6,}{tag}")
            else:
                print(f"  {label:<18} {st['n_city_days']:>7,} {st['n_dates']:>6,} "
                      f"{st['n_exact']:>7,} {'(no exact values -- bucket recovery only)':<62}"
                      f"{st['n_D_negative']:>5,} {st['n_indeterminate']:>6,}{tag}")

        print(f"\n  LEFT TAIL, ENUMERATED -- every city-day with D <= 0")
        tail = sorted((r for r in days if r["D"] is not None and r["D"] <= 0),
                      key=lambda r: (r["D"], r["date"]))
        neg = [r for r in tail if r["D"] < 0]
        print(f"  {len(neg)} city-days with D < 0, {len(tail) - len(neg)} with D == 0, "
              f"out of {sum(1 for r in days if r['D'] is not None):,} with an exact value")
        if neg:
            print(f"  {'city-day':<24} {'auth':<8} {'season':<7} {'settled':>8} {'obs max':>8} "
                  f"{'D':>6} {'margin':>7}")
            for r in neg[:args.max_print]:
                print(f"  {r['event_ticker']:<24} {r['authority']:<8} {r['season']:<7} "
                      f"{r['settled']:>8.1f} {r['observed_max']:>8.1f} {r['D']:>6.1f} "
                      f"{str(r['margin']):>7}")
        counts = collections.Counter(r["D"] for r in tail)
        if counts:
            print("  D<=0 histogram: " + "  ".join(
                f"{d:+.1f}x{n}" for d, n in sorted(counts.items())))

        print(f"\n  VIOLATION MARGIN -- further degrees of negative D needed to flip a")
        print(f"  dominated bucket. 0 = already a violation. Low mass = fragile record.")
        print(f"  'unreach' = city-days where no amount of downward divergence could flip a")
        print(f"  bucket, because the settled value sat in the ladder's open-ended lower tail")
        print(f"  and that bucket's top is at or above the observed max. Those days are")
        print(f"  structurally incapable of producing a violation and are excluded, not counted")
        print(f"  as safe -- treating them as safe would inflate the record for free.")
        print(f"  {'stratum':<18} {'n':>7} {'unreach':>8} {'min':>5} {'p01':>5} {'p05':>5} "
              f"{'p25':>5} {'p50':>5} {'max':>5} {'<=1':>7} {'<=2':>7} {'>=3':>7}")
        for label, d, _, _ in strata:
            mg = summarise_d(d)["margin"]
            if not mg.get("n"):
                print(f"  {label:<18} {'(no margin computable)'}")
                continue
            tag = "  <- not the headline" if label == "POOLED" else ""
            print(f"  {label:<18} {mg['n']:>7,} {mg['unreachable']:>8,} {mg['min']:>5} "
                  f"{mg['p01']:>5.1f} {mg['p05']:>5.1f} {mg['p25']:>5.1f} {mg['p50']:>5.1f} "
                  f"{mg['max']:>5} {mg['le_1_pct']:>6.1f}% {mg['le_2_pct']:>6.1f}% "
                  f"{mg['ge_3_pct']:>6.1f}%{tag}")
        for label, d, _, _ in strata:
            if label in AUTHORITIES:
                mg = summarise_d(d)["margin"]
                if mg.get("n"):
                    print(f"    {label} margin histogram: " + "  ".join(
                        f"{k}:{v}" for k, v in sorted(mg["histogram"].items())[:12]))
        for label, d, _, _ in strata:
            if label not in AUTHORITIES:
                continue
            mg = summarise_d(d)["margin"]
            if not mg.get("n"):
                continue
            if mg["le_2_pct"] >= 50:
                print(f"    !! {label}: {mg['le_2_pct']:.0f}% of eligible city-days sit within "
                      f"2F of a flip (median margin {mg['p50']:.0f}F).")
                print(f"       The zero-violation record is FRAGILE. A systematic 2F downward")
                print(f"       shift in this authority's readings would convert a clean record")
                print(f"       into a leaking one, and the observed left tail already reaches "
                      f"{summarise_d(d).get('min', float('nan')):.1f}F.")
            else:
                print(f"    {label}: {mg['ge_3_pct']:.0f}% of eligible city-days sit 3F+ from a "
                      f"flip -- the record is robust to a shift of that size.")

        print(f"\n  SECONDARY -- dominated buckets that settled Yes (sec.5)")
        print(f"  Violations counted at three units. The triple count is sec.5's literal")
        print(f"  measure; one bad city-day recurs at every afternoon hour, so city-days")
        print(f"  and dates are what correspond to independent events.")
        print(f"  {'stratum':<18} {'dom-hours':>11} {'dates':>6} {'viol':>6} {'v-days':>7} "
              f"{'v-dates':>8} {'rate':>9} {'95% CI (date-clustered)':>26} {'3/k':>8}")
        for label, _, dm, vi in strata:
            s = summarise_dom(dm, vi)
            results[variant]["strata"][label.strip()] = {
                "D": summarise_d([r for r in days
                                  if label == "POOLED" or _match(r, label)]),
                "dominated": s}
            r3d = f"{s['rule_of_three_by_date']:.4f}" if s["rule_of_three_by_date"] else "n/a"
            rate = f"{s['violation_rate_pct']:.4f}%" if s["violation_rate_pct"] is not None else "n/a"
            ci = ("[%.4f%%, %.4f%%]" % (s["rate_ci95_lo_pct"], s["rate_ci95_hi_pct"])
                  if s.get("rate_ci95_lo_pct") is not None else "n/a (no violations)")
            tag = "  <-" if label == "POOLED" else ""
            print(f"  {label:<18} {s['n_dominated_bucket_hours']:>11,} {s['n_dates']:>6,} "
                  f"{s['n_violations']:>6} {s['n_violating_city_days']:>7} "
                  f"{s['n_violating_dates']:>8} {rate:>9} {ci:>26} {r3d:>8}{tag}")

        print(f"\n  sec.5 pre-committed interpretation")
        for label, _, dm, vi in strata:
            s = summarise_dom(dm, vi)
            line = verdict(s["violation_rate_pct"], s["n_dominated_bucket_hours"])
            if s.get("rate_ci95_hi_pct") is not None and s["rate_ci95_hi_pct"] >= 0.5:
                line += "  -- but the CI upper bound reaches %.4f%%, at or past the 0.5%% kill line" % s["rate_ci95_hi_pct"]
            print(f"    {label:<18} {line}")

        if violations:
            shown = violations[:args.max_print]
            print(f"\n  EVERY VIOLATION, INDIVIDUALLY ({len(violations)} total"
                  f"{f', showing {len(shown)}' if len(shown) < len(violations) else ''})")
            print(f"  {'city-day':<24} {'auth':<8} {'season':<7} {'H':>3} {'bucket':<9} "
                  f"{'range':<9} {'M_H':>7} {'obs max':>8} {'settled':>8} {'settled bucket':<14}")
            for v in shown:
                print(f"  {v['event_ticker']:<24} {v['authority']:<8} {v['season']:<7} "
                      f"{v['hour']:>3} {v['bucket']:<9} {v['bucket_range']:<9} "
                      f"{v['M_H']:>7.1f} {v['observed_max']:>8.1f} "
                      f"{str(v['settled_value']):>8} {str(v['settled_bucket']):<14}")
        else:
            print("\n  EVERY VIOLATION, INDIVIDUALLY: none. No dominated bucket settled Yes.")
        results[variant]["violations"] = violations

    print(f"\n{'=' * 108}\nPOWER -- what these bounds actually support")
    for auth in AUTHORITIES:
        s = results["unrounded"]["strata"][auth]["dominated"]
        k = s["n_dates"]
        if not k:
            continue
        if s["rule_of_three_by_date"]:
            print(f"  {auth:<8} {k:>4} independent dates -> honest 95% upper bound "
                  f"{100 * s['rule_of_three_by_date']:>6.2f}% per date"
                  f"   (the per-triple figure {100 * s['rule_of_three_by_triple']:.5f}% "
                  f"is an artefact of treating one weather day as {s['n_dominated_bucket_hours'] // max(k,1)} "
                  f"observations)")
    twc = results["unrounded"]["strata"]["TWC"]["dominated"]
    if twc["n_dates"] and twc["n_dates"] < 30:
        print(f"\n  THE TWC STRATUM IS UNDERPOWERED AND MORE HISTORY DOES NOT FIX IT.")
        print(f"  {twc['n_dates']} independent dates gives a rule-of-three bound of "
              f"{100 * 3 / twc['n_dates']:.0f}% per date. TWC settlement began")
        print(f"  ~2026-08-13, so this stratum grows only with the calendar, at ~21 city-days")
        print(f"  per day. Read a clean TWC result as 'no evidence of a leak', never as")
        print(f"  'the floor holds'. Correction 1 is explicit that the deep archive answers")
        print(f"  seasonality and strategy questions and does not answer this one.")

    # What the NWS stratum implies about the TWC stratum.
    print(f"\n{'=' * 108}")
    print("WHAT NWS SAYS ABOUT TWC -- the strata are not independent evidence")
    for variant in ("unrounded",):
        days, dom_rows, violations, _ = run(ladders, obs_by_station, station_of, False)
        nws = [r for r in days if r["authority"] == "NWS_CLI" and r["D"] is not None]
        twc = [r for r in days if r["authority"] == "TWC" and r["D"] is not None]
        if not nws or not twc:
            continue
        nws_neg = sum(1 for r in nws if r["D"] < 0)
        rate = nws_neg / len(nws)
        expected = rate * len(twc)
        p_clean = (1.0 - rate) ** len(twc) if rate < 1 else 0.0
        twc_neg = sum(1 for r in twc if r["D"] < 0)
        print(f"  The NWS Climatological Report derives from the same ASOS observations IEM")
        print(f"  serves, so its divergence from them was expected to be near-tautological.")
        print(f"  It diverged anyway: {nws_neg} of {len(nws):,} NWS city-days have D < 0 "
              f"({100 * rate:.3f}%).")
        print(f"\n  Applying that rate to the TWC stratum's {len(twc):,} city-days:")
        print(f"    expected D<0 city-days under the NWS rate : {expected:.2f}")
        print(f"    observed  D<0 city-days in TWC            : {twc_neg}")
        print(f"    P(observing zero | NWS rate)              : {p_clean:.3f}")
        print(f"\n  So TWC's clean record is entirely consistent with a divergence rate")
        print(f"  this sample cannot detect. If the near-tautological source diverges, the")
        print(f"  prior that a genuinely independent commercial source also goes negative")
        print(f"  given more dates should go UP, not down. Read the TWC stratum as")
        print(f"  'underpowered and so far unfalsified', never as 'the floor holds'.")

    disagree = [(lab, results["unrounded"]["strata"][lab]["dominated"]["n_violations"],
                 results["rounded"]["strata"][lab]["dominated"]["n_violations"])
                for lab in results["unrounded"]["strata"]
                if results["unrounded"]["strata"][lab]["dominated"]["n_violations"]
                != results["rounded"]["strata"][lab]["dominated"]["n_violations"]]
    print(f"\n  ROUNDING: variants " + (
        "DISAGREE -- sec.5 says report both and take the pessimistic one: "
        + ", ".join(f"{l} {a} vs {b}" for l, a, b in disagree)
        if disagree else "agree on every Test A outcome"))

    days_u, dom_u, viol_u, _ = run(ladders, obs_by_station, station_of, False)
    write_json(RESULTS, {"n_city_days": len(ladders),
                         "date_range": [str(min(dates)), str(max(dates))],
                         "tiers": dict(tiers), "results": results,
                         "city_days_unrounded": days_u})
    print(f"\n  wrote {short(RESULTS)}")


def _match(row, label):
    label = label.strip()
    if "/" in label:
        a, s = label.split("/")
        return row["authority"] == a and row["season"] == s
    return row["authority"] == label


if __name__ == "__main__":
    main()
