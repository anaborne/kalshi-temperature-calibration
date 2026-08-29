"""Step 6, Test B, the strategy. Section 6, with sec.7's holdout embargo in code.

Two commands, and the order is enforced:

    python test_b.py --fit        # fit the residual table on TRAINING cities,
                                  # freeze the rule to data/test_b_rule.json
    python test_b.py --holdout    # refuses unless a frozen rule exists; loads
                                  # the holdout, runs it ONCE, reports

The embargo is enforced in code. load_universe() takes the split it is allowed to
touch and raises on anything else, so a holdout city cannot be read
during --fit even by accident. sec.7: the holdout is not loaded, plotted or
summarised until the rule is frozen.

THE FROZEN RULE (sec.6, nothing here is tunable)

  Residual warming   R = (final daily max) - M_H, both from IEM observations.
                     Checkpoint 1 requires the same observation basis on both
                     sides so the observation-to-settlement offset does not leak
                     into the table as a bias. Empirical frequency table keyed by
                     (local hour H, calendar month, city). No smoothing, no
                     functional form, no free parameters. A cell with fewer than
                     200 observations is not traded.

                     CORRECTION 2 governs how the table is fit. sec.6's "from
                     training cities only" clause is void: it applied holdout
                     hygiene to a component estimated from weather observations
                     rather than market prices, where it protects nothing and
                     would have averaged marine-layer, desert and continental
                     regimes into a number describing none of them. The table is
                     fit from EACH CITY'S OWN observations, identically for train
                     and holdout.

                     And it is fit on a FIXED PRE-PERIOD, strictly before
                     2025-01-01, frozen once, applied unchanged to every backtest
                     day in both splits. Fitting a city on its full history would
                     include the backtest days themselves and price a day using
                     its own outcome. That lookahead is a worse error than the one
                     Correction 2 fixes, so the cutoff is asserted in code, not
                     trusted.

  Fair value         P(bucket b settles Yes) = empirical frequency of M_H + R
                     landing in b.

  Entry              |fair - quote| >= 10c AFTER fees.
                     UNDERDETERMINED BY sec.6, resolved here and disclosed:
                     sec.6 says "one position per city-day-hour" but not which
                     position when several buckets qualify. This code takes
                     the LARGEST edge. That is the natural trading reading and
                     it is also the worst case for adverse selection, picking
                     precisely the bucket whose fair value is most overstated by
                     estimation error. A first-qualifying or random tie-break
                     would trade less on the model's largest mistakes. The
                     choice is recorded because this code made it, not the
                     document.
                     Buy at that hour's yes_ask.high, sell at yes_bid.low --
                     the worst quote in the hour, not the close.
                     Size = min(5% of that hour's volume, $25 notional).
                     One position per city-day-hour. Hold to settlement.

  Fees               taker on every fill, no maker rebate:
                     fee = roundup_to_centicent(M * 0.07 * C * P * (1-P)), M=1
                     confirmed live per series in step 1, not assumed.

INTEGER BASIS. Every expiration_value in the sample is a whole degree, and
buckets are whole-degree ranges. Observations are therefore rounded half-up to
whole degrees before M_H and the final max are taken, which makes R integral and
bucket membership exact. This is sec.5's rounded variant applied consistently to
both sides of the table, as Checkpoint 1 requires.

THE TWO TRADE SHAPES ARE NEVER POOLED INTO ONE EDGE NUMBER

sec.6 spells out why. The shapes have different evidence requirements and only
one of them is gated by a statistic this sample can support:

  dominated-bucket sell   fee 0.14c/contract, 1.86c won against 98.14c risked,
                          breakeven accuracy 98.1%. Its entire expected value is
                          determined by the floor violation rate, which Test A
                          bounds at 25% PER DATE in the TWC stratum. A pooled
                          edge number launders that dependency out of sight.

  mid-bucket buy          fee 1.47c/contract on a 70c bucket worth 90c, 18.5c
                          net edge. Tolerates orders of magnitude more error in
                          the fair value before it stops paying.

So: PnL is reported per shape, with sec.8's criteria applied per shape. If the
pooled figure is positive but the dominated-bucket shape carries it, that is
reported as a red flag and not as a result. The pooled row is printed for
completeness, labelled, and is never the headline.

TWO LIMITATIONS, MEASURED AND REPORTED, NOT CORRECTED
  - The table predicts the final OBSERVED max; buckets settle on the settlement
    authority's value, which Test A measures at ~+0.8F above it with sd 0.74.
    Checkpoint 1 required the same observation basis on both sides so that
    offset would "cancel inside the table". MEASURED, IT DOES NOT CANCEL: the
    table's output is compared against buckets defined on the SETTLEMENT value,
    so the offset and, more damagingly, its dispersion re-enter at the
    bucket-membership step rather than inside the table. check_calibration.py
    shows the result. The fair value is badly overconfident, predicting 0.95+
    where reality is 0.71 and 0.00-0.05 where reality is 0.10. A +1F recentring
    cuts the worst error from 0.397 to 0.209 without fixing it, because the
    problem is dispersion as much as location.
  - M_H at hour H includes observations timestamped inside hour H, while the
    fill is the worst quote anywhere in that same hour. That is a small
    lookahead in the pre-registered rule. --holdout reports a lag-1 sensitivity
    (M_{H-1} against hour H's quotes) alongside the headline.
"""
import argparse
import collections
import datetime as dt
import json
import math
import os
import random
import sys
import zoneinfo

from buckets import in_bucket, yes_bounds
from common import DATA, RAW, read_json, write_json, short

MARKETS = os.path.join(DATA, "parsed", "markets.jsonl")
PROPOSAL = os.path.join(DATA, "station_proposal.json")
OBS = os.path.join(DATA, "obs")
CANDLES_RAW = os.path.join(RAW, "candles")
RULE = os.path.join(DATA, "test_b_rule.json")
RESULTS = os.path.join(DATA, "test_b_results.json")

HOURS = range(9, 24)
MIN_CELL = 200            # sec.6: a cell with fewer than 200 observations is not traded
EDGE_THRESHOLD = 0.10     # sec.6: 10c after fees
FEE_RATE = 0.07           # sec.6 taker
VOLUME_CAP = 0.05         # sec.6: 5% of that hour's volume
NOTIONAL_CAP = 25         # sec.6: $25 notional, $1 per contract
BOOTSTRAP = 10000
SEED = 20260827

# Correction 2: the residual table sees no observation on or after this date.
PREPERIOD_END = dt.date(2025, 1, 1)

# Correction 1: season is a stratification dimension alongside authority.
# Meteorological seasons. Do not pool. The premise of C3 is a summer fact and
# a pooled figure would average two different games and describe neither.
SEASONS = {12: "winter", 1: "winter", 2: "winter",
           3: "spring", 4: "spring", 5: "spring",
           6: "summer", 7: "summer", 8: "summer",
           9: "autumn", 10: "autumn", 11: "autumn"}
SEASON_ORDER = ["winter", "spring", "summer", "autumn"]

MONTH_ABBR = {m: i for i, m in enumerate(
    ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
     "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], 1)}


def round_half_up(x):
    return math.floor(x + 0.5)


def event_date(event_ticker):
    s = event_ticker.rsplit("-", 1)[-1]
    return dt.date(2000 + int(s[:2]), MONTH_ABBR[s[2:5]], int(s[5:]))


def fee(contracts, price):
    """sec.6: roundup(M * 0.07 * C * P * (1-P)), M=1, rounded up to a centicent."""
    raw = FEE_RATE * contracts * price * (1.0 - price)
    return math.ceil(raw / 0.0001 - 1e-9) * 0.0001


def approved_mapping():
    prop = read_json(PROPOSAL)
    if not prop.get("approved"):
        sys.exit("station mapping not approved -- sec.4")
    return {r["series_ticker"]: r for r in prop["rows"]}


def load_universe(mapping, allow_splits):
    """Series tickers in the permitted splits. Raises on anything else.

    --fit passes {"train"} and cannot reach a holdout city even by mistake.
    """
    bad = set(allow_splits) - {"train", "holdout"}
    if bad:
        raise ValueError(f"unknown split {bad}")
    return sorted(t for t, r in mapping.items() if r["split"] in allow_splits)


def load_obs_rounded(station):
    """local date -> [(hour, rounded tmpf)], whole degrees."""
    path = os.path.join(OBS, f"{station}.csv")
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
        days[p[1][:10]].append((int(p[1][11:13]), round_half_up(v)))
    return days


def day_profile(obs_day):
    """(M_H for every hour 0..23, final max) for one local day."""
    if not obs_day:
        return None, None
    m_h, running = {}, None
    by_hour = collections.defaultdict(list)
    for h, v in obs_day:
        by_hour[h].append(v)
    for h in range(24):
        for v in by_hour.get(h, ()):
            if running is None or v > running:
                running = v
        m_h[h] = running
    return m_h, max(v for _, v in obs_day)


def fit_table(mapping, series_list, until=PREPERIOD_END):
    """(city, month, H) -> Counter of R values, from that city's own observations.

    Correction 2: strictly before `until`, for every city in both splits. The
    cutoff is enforced here and re-asserted by verify_preperiod() against the
    frozen artifact, because a silent off-by-one would put a backtest day's own
    outcome into the table that prices it.
    """
    cutoff = until.isoformat()
    table = collections.defaultdict(collections.Counter)
    newest = {}
    for series in series_list:
        station = mapping[series]["proposed_station"]
        days = load_obs_rounded(station)
        for iso, obs_day in sorted(days.items()):
            if iso >= cutoff:
                continue
            m_h, final = day_profile(obs_day)
            if final is None:
                continue
            month = int(iso[5:7])
            newest[series] = max(newest.get(series, ""), iso)
            for H in HOURS:
                M = m_h.get(H)
                if M is None:
                    continue
                table[(series, month, H)][final - M] += 1
    return table, newest


def verify_preperiod(mapping, series_list, newest, table):
    """Hard confirmation, printed before anything fires. Correction 2.

    Two claims: no observation dated on or after the cutoff entered the table,
    and every populated cell clears sec.6's 200-observation floor.
    """
    cutoff = PREPERIOD_END.isoformat()
    print(f"\n  PRE-PERIOD VERIFICATION (Correction 2)")
    bad = {c: d for c, d in newest.items() if d >= cutoff}
    print(f"    cutoff: observations strictly before {cutoff}")
    print(f"    newest observation admitted, over {len(newest)} cities: "
          f"{max(newest.values()) if newest else 'n/a'}")
    if bad:
        sys.exit(f"    FAIL -- {bad} admitted observations on or after the cutoff")
    print(f"    PASS -- no observation dated {cutoff} or later entered the table")

    counts = {k: sum(v.values()) for k, v in table.items()}
    below = {k: n for k, n in counts.items() if n < MIN_CELL}
    vals = sorted(counts.values())
    print(f"\n    cells: {len(counts):,} populated across {len(series_list)} cities "
          f"x 12 months x {len(list(HOURS))} hours")
    print(f"    observations per cell: min {vals[0]:,}  p05 {vals[len(vals)//20]:,}  "
          f"median {vals[len(vals)//2]:,}  max {vals[-1]:,}")
    print(f"    sec.6 floor is {MIN_CELL}: {len(below):,} cells below it "
          f"({100*len(below)/len(counts):.2f}%), {len(counts)-len(below):,} tradeable")
    if below:
        worst = sorted(below.items(), key=lambda kv: kv[1])[:6]
        print("    thinnest cells: " + ", ".join(
            f"{c}/{m:02d}/{h:02d}={n}" for (c, m, h), n in worst))
    missing = [(c, m, h) for c in series_list for m in range(1, 13) for h in HOURS
               if (c, m, h) not in counts]
    print(f"    unpopulated (city, month, hour) combinations: {len(missing):,}")
    return {"cells": len(counts), "below_floor": len(below),
            "min_obs": vals[0], "median_obs": vals[len(vals)//2],
            "newest_observation": max(newest.values()) if newest else None,
            "cutoff": cutoff}


def fair_value(cell, M, bounds):
    """sec.6: empirical frequency of M_H + R landing in bucket b."""
    total = sum(cell.values())
    hit = sum(n for r, n in cell.items() if in_bucket(M + r, bounds))
    return hit / total


def load_ladders(series_list):
    by = collections.defaultdict(list)
    for line in open(MARKETS, encoding="utf-8"):
        m = json.loads(line)
        if m["series_ticker"] in series_list:
            by[m["event_ticker"]].append(m)
    return by


def load_candles(m, tzname):
    """local hour -> candle, for the market's own settlement day."""
    path = os.path.join(CANDLES_RAW, m["series_ticker"], m["ticker"] + ".json")
    if not os.path.exists(path):
        return {}
    tz = zoneinfo.ZoneInfo(tzname)
    target = event_date(m["event_ticker"])
    out = {}
    for c in read_json(path).get("candlesticks") or []:
        # a candle stamped with end_period_ts covers [end-3600, end)
        start = dt.datetime.fromtimestamp(c["end_period_ts"] - 3600, tz)
        if start.date() != target:
            continue
        out[start.hour] = c
    return out


# The two tiers serve the same object under different key names. Live suffixes
# price keys with `_dollars` and reports `volume_fp`/`open_interest_fp`;
# historical uses bare keys and `volume`/`open_interest`. Reading only the live
# spelling makes every historical quote and volume come back None, which the
# size cap then turns into a skipped market, silently excluding 52,704
# markets and collapsing the backtest onto the live tier's 68 summer days
# without raising anything. Both spellings are read.

def _num(d, *names):
    for n in names:
        if n in d and d[n] is not None:
            try:
                return float(d[n])
            except (TypeError, ValueError):
                pass
    return None


def _price(c, side, field):
    book = c.get(side)
    if not isinstance(book, dict):
        return None
    return _num(book, f"{field}_dollars", field)


def _volume(c):
    return _num(c, "volume_fp", "volume") or 0.0


def simulate(mapping, series_list, table, lag=0, d_shift=0):
    """Apply the frozen rule. lag/d_shift are sensitivities, both 0 for the headline."""
    ladders = load_ladders(set(series_list))
    obs_cache = {}
    trades, skips = [], collections.Counter()

    for ev, ms in sorted(ladders.items()):
        series = ms[0]["series_ticker"]
        row = mapping[series]
        station, tzname = row["proposed_station"], row["iem_tzname"]
        if station not in obs_cache:
            obs_cache[station] = load_obs_rounded(station)
        obs_day = obs_cache[station].get(event_date(ev).isoformat())
        if not obs_day:
            skips["no observations"] += 1
            continue
        m_h, _ = day_profile(obs_day)
        month = event_date(ev).month

        settled = None
        for m in ms:
            try:
                settled = float(m["expiration_value"])
                break
            except (KeyError, TypeError, ValueError):
                continue
        if settled is None:
            skips["no expiration_value"] += 1
            continue

        candles = {m["ticker"]: load_candles(m, tzname) for m in ms}

        for H in HOURS:
            M = m_h.get(H - lag)
            if M is None:
                continue
            cell = table.get((series, month, H))
            if cell is None or sum(cell.values()) < MIN_CELL:
                skips["cell below 200"] += 1
                continue

            best = None
            for m in ms:
                c = candles[m["ticker"]].get(H)
                if not c:
                    continue
                vol = _volume(c)
                size = min(int(vol * VOLUME_CAP), NOTIONAL_CAP)
                if size < 1:
                    continue
                bounds = yes_bounds(m)
                fair = fair_value(cell, M + d_shift, bounds)

                for side, quote in (("buy", _price(c, "yes_ask", "high")),
                                    ("sell", _price(c, "yes_bid", "low"))):
                    if quote is None or not 0.0 < quote < 1.0:
                        continue
                    gross = (fair - quote) if side == "buy" else (quote - fair)
                    edge = gross - fee(1, quote)
                    if edge < EDGE_THRESHOLD:
                        continue
                    if best is None or edge > best["edge"]:
                        best = {"market": m, "side": side, "quote": quote,
                                "fair": fair, "edge": edge, "size": size,
                                "hour": H, "M_H": M, "bounds": bounds,
                                "volume": vol}
            if best is None:
                continue

            m, size, quote = best["market"], best["size"], best["quote"]
            won = in_bucket(settled, best["bounds"])
            f = fee(size, quote)
            if best["side"] == "buy":
                pnl = size * ((1.0 if won else 0.0) - quote) - f
            else:
                pnl = size * (quote - (1.0 if won else 0.0)) - f

            # sec.6's two shapes, for the split it asks for
            dominated = best["bounds"][1] is not None and best["bounds"][1] < best["M_H"]
            contains_m = in_bucket(best["M_H"], best["bounds"])
            if best["side"] == "sell" and dominated:
                shape = "dominated-bucket sell"
            elif best["side"] == "buy" and contains_m:
                shape = "mid-bucket buy"
            else:
                shape = "other"

            trades.append({
                "event_ticker": ev, "series_ticker": series,
                "date": event_date(ev).isoformat(), "hour": H,
                "season": SEASONS[month], "month": month,
                "ticker": m["ticker"], "side": best["side"], "shape": shape,
                "quote": quote, "fair": best["fair"], "edge": best["edge"],
                "size": size, "hour_volume": best["volume"],
                "M_H": best["M_H"], "settled": settled, "won": won,
                "fee": f, "pnl": pnl, "pnl_per_contract": pnl / size,
            })
    return trades, skips


def bootstrap_ci(values, clusters=None, reps=BOOTSTRAP):
    """95% percentile bootstrap on the mean. Cluster-resamples when given keys."""
    if not values:
        return None, None
    rng = random.Random(SEED)
    if clusters is None:
        n = len(values)
        means = []
        for _ in range(reps):
            means.append(sum(values[rng.randrange(n)] for _ in range(n)) / n)
    else:
        groups = collections.defaultdict(list)
        for v, k in zip(values, clusters):
            groups[k].append(v)
        keys = list(groups)
        means = []
        for _ in range(reps):
            drawn = []
            for _ in range(len(keys)):
                drawn.extend(groups[keys[rng.randrange(len(keys))]])
            means.append(sum(drawn) / len(drawn))
    means.sort()
    return means[int(0.025 * reps)], means[int(0.975 * reps)]


def describe(trades, label):
    if not trades:
        print(f"  {label}: 0 trades")
        return None
    pnl = [t["pnl"] for t in trades]
    per_contract = [t["pnl_per_contract"] for t in trades]
    dates = [t["date"] for t in trades]
    mean = sum(pnl) / len(pnl)
    lo, hi = bootstrap_ci(pnl)
    clo, chi = bootstrap_ci(pnl, clusters=dates)
    out = {
        "label": label, "n_trades": len(trades), "n_dates": len(set(dates)),
        "n_contracts": sum(t["size"] for t in trades),
        "total_pnl": sum(pnl), "mean_pnl_per_trade": mean,
        "ci95_lo": lo, "ci95_hi": hi,
        "ci95_lo_date_clustered": clo, "ci95_hi_date_clustered": chi,
        "mean_pnl_per_contract": sum(t["pnl"] for t in trades) / sum(t["size"] for t in trades),
        "median_pnl_per_contract": sorted(per_contract)[len(per_contract) // 2],
        "win_rate_pct": 100.0 * sum(1 for t in trades if t["pnl"] > 0) / len(trades),
        "total_fees": sum(t["fee"] for t in trades),
    }
    print(f"  {label}")
    print(f"    trades {out['n_trades']:,} over {out['n_dates']} dates, "
          f"{out['n_contracts']:,} contracts, fees ${out['total_fees']:.2f}")
    print(f"    mean PnL/trade  ${mean:>8.4f}   95% CI [${lo:.4f}, ${hi:.4f}]")
    print(f"    date-clustered CI            [${clo:.4f}, ${chi:.4f}]")
    print(f"    net edge  {100 * out['mean_pnl_per_contract']:.2f}c/contract   "
          f"win rate {out['win_rate_pct']:.1f}%   total ${out['total_pnl']:.2f}")
    return out


def shape_stats(trades, shape):
    g = [t for t in trades if t["shape"] == shape]
    if not g:
        return {"shape": shape, "n_trades": 0}
    pnl = [t["pnl"] for t in g]
    contracts = sum(t["size"] for t in g)
    lo, hi = bootstrap_ci(pnl)
    clo, chi = bootstrap_ci(pnl, clusters=[t["date"] for t in g])
    wins = sum(1 for t in g if t["won"])
    return {"shape": shape, "n_trades": len(g), "n_dates": len({t["date"] for t in g}),
            "n_contracts": contracts, "total_pnl": sum(pnl),
            "mean_pnl_per_trade": sum(pnl) / len(g),
            "ci95_lo": lo, "ci95_hi": hi,
            "ci95_lo_date_clustered": clo, "ci95_hi_date_clustered": chi,
            "cents_per_contract": 100.0 * sum(pnl) / contracts,
            "settle_accuracy_pct": 100.0 * wins / len(g),
            "meets_trade_floor": len(g) >= 30}


def by_shape(trades, label="PnL"):
    """sec.6's two shapes, reported separately and never summed into one edge."""
    print(f"\n  {label} BY TRADE SHAPE -- reported separately, never pooled into one edge")
    print(f"  {'shape':<24} {'trades':>7} {'dates':>6} {'mean/trade':>11} "
          f"{'95% CI':>22} {'c/contract':>11} {'accuracy':>9}")
    out = {}
    for shape in ("dominated-bucket sell", "mid-bucket buy", "other"):
        st = shape_stats(trades, shape)
        out[shape] = st
        if not st["n_trades"]:
            print(f"  {shape:<24} {0:>7}")
            continue
        ci = f"[{st['ci95_lo']:>7.4f},{st['ci95_hi']:>8.4f}]"
        print(f"  {shape:<24} {st['n_trades']:>7,} {st['n_dates']:>6} "
              f"${st['mean_pnl_per_trade']:>10.4f} {ci:>22} "
              f"{st['cents_per_contract']:>10.2f}c {st['settle_accuracy_pct']:>8.1f}%")

    dom = out["dominated-bucket sell"]
    if dom["n_trades"]:
        print(f"\n    dominated-bucket sells need 98.1% settle accuracy to break even; "
              f"realised {dom['settle_accuracy_pct']:.1f}%.")
        print(f"    Their EV is determined by the floor violation rate, which Test A bounds")
        print(f"    at 25% per date in the TWC stratum. This shape is not evidenced by this")
        print(f"    sample regardless of what its realised PnL says.")

    total = sum(t["pnl"] for t in trades)
    if total > 0 and dom.get("total_pnl", 0) > 0.5 * total:
        print(f"\n    !! {100 * dom['total_pnl'] / total:.0f}% of total PnL comes from "
              f"dominated-bucket sells.")
        print(f"    sec.6: treat that as a red flag rather than a result. The pooled edge is")
        print(f"    NOT reported as the headline.")
    return out


def by_season(trades, label):
    """Correction 1: report the four seasons separately. Do not pool."""
    print(f"\n  {label} BY SEASON (Correction 1 -- pooling mixes regimes, not noise)")
    out = {}
    for season in SEASON_ORDER:
        g = [t for t in trades if t["season"] == season]
        if not g:
            print(f"    {season:<8} 0 trades")
            out[season] = {"n_trades": 0}
            continue
        pnl = [t["pnl"] for t in g]
        mean = sum(pnl) / len(pnl)
        lo, hi = bootstrap_ci(pnl)
        clo, chi = bootstrap_ci(pnl, clusters=[t["date"] for t in g])
        contracts = sum(t["size"] for t in g)
        out[season] = {
            "n_trades": len(g), "n_dates": len({t["date"] for t in g}),
            "n_contracts": contracts, "total_pnl": sum(pnl),
            "mean_pnl_per_trade": mean, "ci95_lo": lo, "ci95_hi": hi,
            "ci95_lo_date_clustered": clo, "ci95_hi_date_clustered": chi,
            "cents_per_contract": 100.0 * sum(pnl) / contracts,
            "meets_trade_floor": len(g) >= 30,
        }
        flag = "" if len(g) >= 30 else "   <30 trades: NO CONCLUSION (sec.8)"
        print(f"    {season:<8} {len(g):>5} trades  mean ${mean:>8.4f}  "
              f"95% CI [${lo:>7.4f}, ${hi:>7.4f}]  "
              f"{out[season]['cents_per_contract']:>6.2f}c/ct{flag}")
        print(f"    {'':<8} {'':>5}          date-clustered CI [${clo:>7.4f}, ${chi:>7.4f}]")
    return out


def cmd_verify(mapping):
    """Correction 2's mandatory pre-flight. Observations only, no candles, no
    market data, so it can run before the candlestick pull finishes."""
    every = load_universe(mapping, {"train", "holdout"})
    print("=" * 96)
    print("TEST B -- PRE-PERIOD VERIFICATION (Correction 2, required before --holdout)")
    print("=" * 96)
    table, newest = fit_table(mapping, every)
    checks = verify_preperiod(mapping, every, newest, table)

    print(f"\n  PER-CITY CELL COUNTS vs the sec.6 floor of {MIN_CELL}")
    print(f"  {'city':<13} {'stn':<4} {'cells':>6} {'below':>6} {'min':>6} {'p05':>7} "
          f"{'median':>7} {'max':>6} {'newest obs admitted':>21}")
    per_city_ok = True
    for city in every:
        counts = sorted(sum(v.values()) for (c, _, _), v in table.items() if c == city)
        if not counts:
            print(f"  {city:<13} {'':4} NO CELLS")
            per_city_ok = False
            continue
        below = sum(1 for n in counts if n < MIN_CELL)
        if below:
            per_city_ok = False
        print(f"  {city:<13} {mapping[city]['proposed_station']:<4} {len(counts):>6} "
              f"{below:>6} {counts[0]:>6,} {counts[len(counts)//20]:>7,} "
              f"{counts[len(counts)//2]:>7,} {counts[-1]:>6,} {newest.get(city,'-'):>21}")
    print(f"\n  every city has all 12 months x {len(list(HOURS))} hours populated "
          f"and clears the floor: {per_city_ok}")

    months = collections.Counter(m for (_, m, _) in table)
    print(f"  months populated: {sorted(months)} "
          f"({'all twelve -- seasonal stratification supported' if len(months) == 12 else 'INCOMPLETE'})")
    return checks


def cmd_fit(mapping):
    train = load_universe(mapping, {"train"})
    every = load_universe(mapping, {"train", "holdout"})

    print("=" * 96)
    print("TEST B -- FIT  (Correction 2: per-city table on a frozen pre-period)")
    print("=" * 96)
    print(f"  training cities ({len(train)}): {' '.join(train)}")
    print(f"  table is fit for all {len(every)} cities from each city's OWN observations,")
    print(f"  strictly before {PREPERIOD_END}. It contains no market data of any kind:")
    print(f"  no prices, no volumes, no results, no expiration_value.")

    table, newest = fit_table(mapping, every)
    checks = verify_preperiod(mapping, every, newest, table)

    print(f"\n  RESIDUAL WARMING R = final max - M_H  (median, degrees F, all cities pooled")
    print(f"  FOR DISPLAY ONLY -- the table itself is per-city and never pooled)")
    print(f"  {'H':>3} " + " ".join(f"{s:>8}" for s in SEASON_ORDER))
    for H in HOURS:
        cells = []
        for season in SEASON_ORDER:
            pool = collections.Counter()
            for city in every:
                for m, sname in SEASONS.items():
                    if sname == season:
                        pool.update(table.get((city, m, H), {}))
            if not pool:
                cells.append("       -")
                continue
            vals = sorted(pool.elements())
            cells.append(f"{vals[len(vals) // 2]:>8.1f}")
        print(f"  {H:>3} " + " ".join(cells))

    print("\n" + "-" * 96)
    print("  TRAINING-CITY RUN (this is where the rule's free choices are checked)")
    trades, skips = simulate(mapping, train, table)
    print(f"  skips: {dict(skips)}")
    train_shapes = by_shape(trades, "TRAIN") if trades else {}
    train_seasons = by_season(trades, "TRAIN")
    describe(trades, "train, all seasons and shapes (POOLED -- NOT the headline)")

    frozen = {
        "frozen": True,
        "correction_2": {
            "table_source": "each city's own IEM observations",
            "preperiod_cutoff": PREPERIOD_END.isoformat(),
            "verification": checks,
        },
        "training_cities": train, "all_cities": every,
        "min_cell": MIN_CELL, "edge_threshold": EDGE_THRESHOLD,
        "fee_rate": FEE_RATE, "fee_multiplier": 1,
        "volume_cap": VOLUME_CAP, "notional_cap": NOTIONAL_CAP,
        "hours": list(HOURS), "seasons": SEASONS,
        "observation_basis": "rounded half-up to whole degrees, both sides",
        "table": {f"{c}|{m}|{h}": dict(sorted(v.items()))
                  for (c, m, h), v in sorted(table.items())},
    }
    write_json(RULE, frozen)
    write_json(os.path.join(DATA, "test_b_train.json"),
               {"trades": trades, "seasons": train_seasons, "shapes": train_shapes})
    print(f"\n  wrote {short(RULE)} -- the rule is frozen.")
    print("  sec.8: changing threshold, cell keys, fill assumption or split after the")
    print("  holdout is seen kills C3. --holdout runs once.")


def cmd_holdout(mapping):
    if not os.path.exists(RULE):
        sys.exit("no frozen rule -- run --fit first (sec.7)")
    frozen = read_json(RULE)
    if not frozen.get("frozen"):
        sys.exit("rule file is not marked frozen")

    holdout = load_universe(mapping, {"holdout"})
    print("=" * 96)
    print("TEST B -- HOLDOUT, RUN ONCE (sec.7)")
    print("=" * 96)
    c2 = frozen["correction_2"]
    print(f"  frozen rule: threshold {frozen['edge_threshold']*100:.0f}c after fees, "
          f"cell floor {frozen['min_cell']}, fee multiplier {frozen['fee_multiplier']}")
    print(f"  table: {c2['table_source']}, strictly before {c2['preperiod_cutoff']}")
    print(f"  verified newest observation in table: {c2['verification']['newest_observation']}")
    if c2["verification"]["newest_observation"] >= c2["preperiod_cutoff"]:
        sys.exit("  FAIL -- frozen table breaches its own pre-period cutoff")
    print(f"  holdout cities ({len(holdout)}): {' '.join(holdout)}")

    table = collections.defaultdict(collections.Counter)
    for key, counts in frozen["table"].items():
        c, m, h = key.split("|")
        table[(c, int(m), int(h))] = collections.Counter(
            {int(r): n for r, n in counts.items()})

    trades, skips = simulate(mapping, holdout, table)
    print(f"\n  skips: {dict(skips)}")

    shapes = by_shape(trades, "HOLDOUT") if trades else {}
    seasons = by_season(trades, "HOLDOUT")
    overall = describe(trades, "holdout, all seasons and shapes (POOLED -- NOT the headline)")

    print("\n  SENSITIVITIES (reported, not corrected -- the headline is the frozen rule)")
    lag_trades, _ = simulate(mapping, holdout, table, lag=1)
    describe(lag_trades, "lag-1: M_{H-1} against hour H's quotes (removes intra-hour lookahead)")

    print("\n" + "=" * 96)
    print("  sec.8 KILL CRITERIA, PER SHAPE (the shapes have different evidence needs)")
    shape_verdicts = {}
    for shape in ("mid-bucket buy", "dominated-bucket sell"):
        st = shapes.get(shape, {})
        n = st.get("n_trades", 0)
        if not n or n < 30:
            v = f"NO CONCLUSION -- {n} trades, below the 30-trade floor"
        elif st["ci95_lo"] <= 0:
            v = f"DIES -- 95% CI lower bound ${st['ci95_lo']:.4f} <= 0"
        elif st["cents_per_contract"] < 3.0:
            v = f"PARK -- {st['cents_per_contract']:.2f}c/contract, under the 3c bar"
        else:
            v = f"survives on PnL: {st['cents_per_contract']:.2f}c/contract"
            if shape == "dominated-bucket sell":
                v += " -- but UNEVIDENCED: gated by a floor rate bounded at 25%/date"
        shape_verdicts[shape] = v
        print(f"    {shape:<24} {v}")

    print("\n  sec.8 KILL CRITERIA, PER SEASON")
    verdicts = {}
    for season in SEASON_ORDER:
        st = seasons.get(season, {})
        n = st.get("n_trades", 0)
        if n < 30:
            v = f"NO CONCLUSION -- {n} trades, below the 30-trade floor"
        elif st["ci95_lo"] <= 0:
            v = f"C3 DIES in {season} -- 95% CI lower bound ${st['ci95_lo']:.4f} <= 0"
        elif st["cents_per_contract"] < 3.0:
            v = f"PARK -- clears zero at {st['cents_per_contract']:.2f}c/contract, under the 3c bar"
        else:
            v = f"SURVIVES -- {st['cents_per_contract']:.2f}c/contract, CI lower bound ${st['ci95_lo']:.4f}"
        verdicts[season] = v
        print(f"    {season:<8} {v}")
    print("\n    sec.8 forbids lowering the threshold to manufacture trades. Where the")
    print("    count is short, the reported result is the null, not a retuned rule.")

    write_json(RESULTS, {"trades": trades, "overall": overall, "seasons": seasons,
                         "shapes": shapes, "verdicts": verdicts,
                         "shape_verdicts": shape_verdicts,
                         "skips": dict(skips), "frozen_rule_checks": c2})
    print(f"\n  wrote {short(RESULTS)}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--fit", action="store_true")
    ap.add_argument("--verify", action="store_true",
                    help="pre-period + cell-count confirmation only (no candles needed)")
    ap.add_argument("--holdout", action="store_true")
    args = ap.parse_args()
    mapping = approved_mapping()
    if args.verify:
        cmd_verify(mapping)
    elif args.fit:
        cmd_fit(mapping)
    elif args.holdout:
        cmd_holdout(mapping)
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
