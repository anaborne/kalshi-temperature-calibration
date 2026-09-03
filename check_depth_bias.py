"""Did deepening the observation archive to 1995 trade variance for bias?

Deepening cut the residual table's sampling noise roughly in half (cells went
from ~465 to ~930 observations). That is only a gain if the older data measures
the same thing. Two ways it might not:

  REPORTING DENSITY. ASOS reporting frequency has risen over time, with more
  SPECIs, and some stations moved from sparse synoptic schedules to routine hourlies. A
  day observed 12 times has a systematically LOWER running maximum than the same
  day observed 30 times, because the max of a smaller sample of a diurnal curve
  is lower. That understates M_H in old data, which INFLATES R = final max - M_H,
  which biases every fair value the table produces upward.

  DISTRIBUTION SHIFT. Even at equal density, the residual distribution itself may
  differ between eras for climate or instrumentation reasons.

So: observations per station-year, and the residual distribution fit separately
on 1995-2009 and 2010-2024, compared at the hours the strategy trades.

This runs BEFORE the rule is frozen and reports; it does not choose.
"""
import collections
import os
import statistics

from common import DATA, read_json
from test_b import HOURS, day_profile, load_obs_rounded

OBS = os.path.join(DATA, "obs")
ERA_A = (1995, 2009)
ERA_B = (2010, 2024)
# The era boundary this file reports on. It used to read test_b.PREPERIOD_END,
# which happened to be 2025-01-01. Correction 4 moved that cutoff to 2021-08-01,
# and following it here would silently shorten era B to 2010-2020 and change
# every figure section 3 of RESULTS.md quotes. The eras are named above, so the
# end of the sample is stated here rather than borrowed.
ARCHIVE_END = 2025


def main():
    prop = read_json(os.path.join(DATA, "station_proposal.json"))
    rows = prop["rows"]

    print("=" * 100)
    print("1. REPORTING DENSITY -- observations per day, by station-year")
    print("=" * 100)
    per_year = collections.defaultdict(list)      # year -> [obs/day, ...]
    per_station_era = collections.defaultdict(list)
    for r in rows:
        stn = r["proposed_station"]
        days = load_obs_rounded(stn)
        for iso, obs in days.items():
            y = int(iso[:4])
            if y >= ARCHIVE_END:
                continue
            per_year[y].append(len(obs))
            era = "A" if y <= ERA_A[1] else "B"
            per_station_era[(stn, era)].append(len(obs))

    print(f"  {'year':>6} {'city-days':>10} {'mean obs/day':>13} {'median':>8}")
    for y in sorted(per_year):
        v = per_year[y]
        print(f"  {y:>6} {len(v):>10,} {statistics.mean(v):>13.1f} {statistics.median(v):>8.0f}")

    a = [n for (s, e), vs in per_station_era.items() if e == "A" for n in vs]
    b = [n for (s, e), vs in per_station_era.items() if e == "B" for n in vs]
    print(f"\n  {ERA_A[0]}-{ERA_A[1]}  mean {statistics.mean(a):.2f} obs/day  (n={len(a):,} city-days)")
    print(f"  {ERA_B[0]}-{ERA_B[1]}  mean {statistics.mean(b):.2f} obs/day  (n={len(b):,} city-days)")
    gap = statistics.mean(b) - statistics.mean(a)
    print(f"  difference: {gap:+.2f} obs/day ({100 * gap / statistics.mean(a):+.1f}%)")

    print(f"\n  worst per-station gaps (recent minus old, obs/day):")
    gaps = []
    for r in rows:
        s = r["proposed_station"]
        va, vb = per_station_era.get((s, "A")), per_station_era.get((s, "B"))
        if va and vb:
            gaps.append((statistics.mean(vb) - statistics.mean(va), s,
                         statistics.mean(va), statistics.mean(vb)))
    for g, s, ma, mb in sorted(gaps, reverse=True)[:6]:
        print(f"    {s:<4} {ma:>6.1f} -> {mb:>6.1f}   {g:+.1f}")

    print("\n" + "=" * 100)
    print("2. RESIDUAL DISTRIBUTION BY ERA -- R = final max - M_H, at traded hours")
    print("=" * 100)
    era_R = {"A": collections.defaultdict(collections.Counter),
             "B": collections.defaultdict(collections.Counter)}
    for r in rows:
        stn = r["proposed_station"]
        for iso, obs in load_obs_rounded(stn).items():
            y = int(iso[:4])
            if y >= ARCHIVE_END or y < ERA_A[0]:
                continue
            era = "A" if y <= ERA_A[1] else "B"
            m_h, final = day_profile(obs)
            if final is None:
                continue
            for H in HOURS:
                M = m_h.get(H)
                if M is not None:
                    era_R[era][H][final - M] += 1

    def stats(counter):
        vals = sorted(counter.elements())
        n = len(vals)
        return (n, statistics.mean(vals), vals[n // 2],
                vals[int(0.9 * n)], 100.0 * sum(1 for v in vals if v == 0) / n)

    print(f"  {'H':>3} | {'n':>9} {'mean':>6} {'med':>4} {'p90':>4} {'P(R=0)':>7} "
          f"| {'n':>9} {'mean':>6} {'med':>4} {'p90':>4} {'P(R=0)':>7} | {'dMean':>6} {'dP(R=0)':>8}")
    print(f"  {'':>3} | {ERA_A[0]}-{ERA_A[1]:<28} | {ERA_B[0]}-{ERA_B[1]:<28} | shift")
    worst = 0.0
    for H in HOURS:
        na, ma, mda, p9a, z_a = stats(era_R["A"][H])
        nb, mb, mdb, p9b, z_b = stats(era_R["B"][H])
        d = mb - ma
        worst = max(worst, abs(d))
        print(f"  {H:>3} | {na:>9,} {ma:>6.2f} {mda:>4.0f} {p9a:>4.0f} {z_a:>6.1f}% "
              f"| {nb:>9,} {mb:>6.2f} {mdb:>4.0f} {p9b:>4.0f} {z_b:>6.1f}% "
              f"| {d:>+6.2f} {z_b - z_a:>+7.1f}pp")

    print(f"\n  largest mean shift across traded hours: {worst:.2f} F")
    print(f"  For scale: buckets are 2F wide, so a shift of 1.0F would move a")
    print(f"  material share of probability mass across a bucket boundary.")

    noise_floor(rows)
    signed_shift(rows)


def _rows_for(stn, lo, hi=ARCHIVE_END):
    out = []
    for iso, obs in load_obs_rounded(stn).items():
        y = int(iso[:4])
        if not (lo <= y < hi):
            continue
        m_h, final = day_profile(obs)
        if final is not None:
            out.append((int(iso[5:7]), m_h, final))
    return out


def _table(rs):
    t = collections.defaultdict(collections.Counter)
    for mo, m_h, final in rs:
        for H in HOURS:
            M = m_h.get(H)
            if M is not None:
                t[(mo, H)][final - M] += 1
    return t


def _cells(a, b):
    from test_b import fair_value
    for mo in range(1, 13):
        for H in HOURS:
            x, y = a.get((mo, H)), b.get((mo, H))
            if not x or not y:
                continue
            for off in range(0, 14, 2):
                bd = (80 + off, 80 + off + 1)
                yield fair_value(x, 80, bd) - fair_value(y, 80, bd)


def _nested_null(pool, n_outer, n_inner, rng, splits):
    """Sampling spread of the max-cell statistic, at the comparison's own shape.

    The comparison this benchmarks is a table on 1995-2024 against a table on
    2010-2024: a superset against a subset of itself, sharing every day the
    smaller one has. A disjoint half-split of the modern era matches neither the
    sizes nor the overlap, and the sampling spread of a per-cell difference is
    several times wider for two disjoint halves than for a nested pair, so a
    floor built that way is several times too high. Both sets here are still
    drawn from the same era, so bias remains impossible by construction.
    """
    out = []
    for _ in range(splits):
        outer = [pool[rng.randrange(len(pool))] for _ in range(n_outer)]
        inner = outer[:]
        rng.shuffle(inner)
        out.append(100 * max(abs(d) for d in _cells(_table(outer),
                                                    _table(inner[:n_inner]))))
    return out


def noise_floor(rows, stations=("NYC", "MDW", "LAX", "SAN", "PHL"), splits=5):
    import random
    print("\n" + "=" * 100)
    print("3. NOISE FLOOR -- what this statistic reports when bias is IMPOSSIBLE")
    print("=" * 100)
    print("  Two tables drawn from the SAME era (2010-2024), at the sizes and the")
    print("  nesting of the depth comparison each column judges. Any divergence is pure")
    print("  sampling noise. If it exceeds the depth difference, the max statistic")
    print("  cannot support a conclusion either way.")
    print("  Correction: this floor was previously built from a disjoint half-split of")
    print("  the modern era, which is neither the size nor the overlap of the tables it")
    print("  was compared against, and it came out several times too wide.")
    rng = random.Random(20260827)
    print(f"\n  {'stn':<4} {'floor vs 1995':>14} {'1995 vs 2010':>13} "
          f"{'floor vs 2005':>14} {'2005 vs 2010':>13}   (mean of %d draws)" % splits)
    for stn in stations:
        modern = _rows_for(stn, 2010)
        r95, r05 = _rows_for(stn, 1995), _rows_for(stn, 2005)
        ref = _table(modern)
        d95 = 100 * max(abs(d) for d in _cells(_table(r95), ref))
        d05 = 100 * max(abs(d) for d in _cells(_table(r05), ref))
        f95 = _nested_null(modern, len(r95), len(modern), rng, splits)
        f05 = _nested_null(modern, len(r05), len(modern), rng, splits)
        print(f"  {stn:<4} {statistics.mean(f95):>13.2f}c {d95:>12.2f}c "
              f"{statistics.mean(f05):>13.2f}c {d05:>12.2f}c")


def signed_shift(rows):
    import math
    print("\n" + "=" * 100)
    print("4. SYSTEMATIC BIAS -- signed mean shift, 1995-table minus 2010-table")
    print("=" * 100)
    print(f"  {'city':<13} {'stn':<4} {'split':<8} {'signed dP':>10} {'mean|dP|':>9} "
          f"{'dMeanR@13':>11} {'t':>6}")
    for r in rows:
        stn = r["proposed_station"]
        t95, t10 = _table(_rows_for(stn, 1995)), _table(_rows_for(stn, 2010))
        ds = list(_cells(t95, t10))
        xa = [v for mo in range(1, 13) for v in t95.get((mo, 13), {}).elements()]
        xb = [v for mo in range(1, 13) for v in t10.get((mo, 13), {}).elements()]
        se = math.sqrt(statistics.pvariance(xa) / len(xa) + statistics.pvariance(xb) / len(xb))
        d = statistics.mean(xa) - statistics.mean(xb)
        print(f"  {r['series_ticker']:<13} {stn:<4} {r['split']:<8} "
              f"{100 * statistics.mean(ds):>+9.3f}c "
              f"{100 * statistics.mean(abs(x) for x in ds):>8.3f}c "
              f"{d:>+10.3f}F {d / se if se else 0:>+6.1f}")


if __name__ == "__main__":
    main()
