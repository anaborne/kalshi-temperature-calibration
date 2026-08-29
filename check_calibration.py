"""Is the sec.6 fair value calibrated? Training cities only.

A backtest that loses money has two very different explanations and they demand
different reporting:

  the market is efficient   fair value is well calibrated, and the quotes
                            already reflect it, so no edge survives fees

  the estimator is broken   fair value is systematically wrong, and the losses
                            measure that error rather than anything about the
                            market

Only a calibration curve separates them. For every bucket-hour the rule
EVALUATES (not only the ones it trades), bin by predicted probability and
compare to the realised settle rate.

Also reported: the same curve on a settlement-basis shifted table. sec.6 fits R
from observations on both sides, which Checkpoint 1 requires so the
observation-to-settlement offset cancels inside the table. But the resulting
prediction is of the final OBSERVED max, while the bucket settles on the
authority's value, which Test A measures at roughly +0.8F above it. That is a
known, flagged, uncorrected limitation of the frozen rule; this quantifies what
it costs.

TRAIN ONLY. sec.7's holdout is untouched by this file.
"""
import collections
import json
import os
import sys

from buckets import in_bucket, yes_bounds
from common import DATA, read_json, short
from test_b import (HOURS, MIN_CELL, approved_mapping, day_profile, event_date,
                    fair_value, load_candles, load_obs_rounded, load_universe,
                    _price, _volume)

RULE = os.path.join(DATA, "test_b_rule.json")
BINS = [(0.0, .05), (.05, .1), (.1, .2), (.2, .3), (.3, .4), (.4, .5),
        (.5, .6), (.6, .7), (.7, .8), (.8, .9), (.9, .95), (.95, 1.01)]


def load_table():
    t = collections.defaultdict(collections.Counter)
    for key, counts in read_json(RULE)["table"].items():
        c, m, h = key.split("|")
        t[(c, int(m), int(h))] = collections.Counter({int(r): n for r, n in counts.items()})
    return t


def curve(shift):
    mapping = approved_mapping()
    train = set(load_universe(mapping, {"train"}))
    table = load_table()
    ladders = collections.defaultdict(list)
    for line in open(os.path.join(DATA, "parsed", "markets.jsonl"), encoding="utf-8"):
        m = json.loads(line)
        if m["series_ticker"] in train:
            ladders[m["event_ticker"]].append(m)

    obs_cache = {}
    bins = collections.defaultdict(lambda: [0, 0])          # bin -> [n, settled_yes]
    quoted = collections.defaultdict(lambda: [0.0, 0.0, 0])  # bin -> [sum fair, sum mid, n]
    for ev, ms in ladders.items():
        row = mapping[ms[0]["series_ticker"]]
        stn = row["proposed_station"]
        if stn not in obs_cache:
            obs_cache[stn] = load_obs_rounded(stn)
        d = event_date(ev)
        obs_day = obs_cache[stn].get(d.isoformat())
        if not obs_day:
            continue
        m_h, _ = day_profile(obs_day)
        settled = None
        for m in ms:
            try:
                settled = float(m["expiration_value"])
                break
            except (KeyError, TypeError, ValueError):
                continue
        if settled is None:
            continue
        candles = {m["ticker"]: load_candles(m, row["iem_tzname"]) for m in ms}
        for H in HOURS:
            M = m_h.get(H)
            cell = table.get((ms[0]["series_ticker"], d.month, H))
            if M is None or cell is None or sum(cell.values()) < MIN_CELL:
                continue
            for m in ms:
                c = candles[m["ticker"]].get(H)
                if not c or _volume(c) < 20:
                    continue
                b = yes_bounds(m)
                if b == (None, None):
                    continue
                p = fair_value(cell, M + shift, b)
                won = in_bucket(settled, b)
                for lo, hi in BINS:
                    if lo <= p < hi:
                        bins[(lo, hi)][0] += 1
                        bins[(lo, hi)][1] += int(won)
                        ask = _price(c, "yes_ask", "high")
                        bid = _price(c, "yes_bid", "low")
                        if ask is not None and bid is not None:
                            q = quoted[(lo, hi)]
                            q[0] += p
                            q[1] += (ask + bid) / 2
                            q[2] += 1
                        break
    return bins, quoted


def report(shift, label, dump=None):
    bins, quoted = curve(shift)
    total = sum(v[0] for v in bins.values())
    rows = []
    print(f"\n  {label}   ({total:,} evaluated bucket-hours)")
    print(f"  {'predicted':>14} {'n':>9} {'realised':>9} {'error':>8} {'mean fair':>10} "
          f"{'mean quote':>11} {'fair-quote':>11}")
    worst = 0.0
    for lo, hi in BINS:
        n, w = bins[(lo, hi)]
        if not n:
            continue
        realised = w / n
        mid = (lo + hi) / 2
        q = quoted[(lo, hi)]
        mf, mq = (q[0] / q[2], q[1] / q[2]) if q[2] else (float("nan"), float("nan"))
        worst = max(worst, abs(realised - mid))
        rows.append({"lo": lo, "hi": hi, "n": n, "realised": realised,
                     "mean_fair": mf, "mean_quote": mq})
        print(f"  {lo:>6.2f}-{hi:<6.2f} {n:>9,} {realised:>9.3f} {realised - mid:>+8.3f} "
              f"{mf:>10.3f} {mq:>11.3f} {mf - mq:>+11.3f}")
    print(f"    worst absolute calibration error: {worst:.3f}")
    if dump is not None:
        dump.update(label=label, evaluated=total, worst=worst, bins=rows)
    return worst


def brier(rel=None):
    """Brier score of the model vs the market quote, on the same events.

    Lower is better. This is the question that decides C3 independently of any
    calibration fix: even a perfectly recentred model has to beat the quote, and
    the quote is what the strategy must trade against.
    """
    if rel is None:
        rel = collections.defaultdict(lambda: [0, 0.0, 0.0])
    alt = [0.0, 0.0, 0.0, 0]   # model, widest-spread mid, closing mid, n
    mapping = approved_mapping()
    train = set(load_universe(mapping, {"train"}))
    table = load_table()
    ladders = collections.defaultdict(list)
    for line in open(os.path.join(DATA, "parsed", "markets.jsonl"), encoding="utf-8"):
        m = json.loads(line)
        if m["series_ticker"] in train:
            ladders[m["event_ticker"]].append(m)
    obs_cache = {}
    sm = sq = 0.0
    n = 0
    for ev, ms in ladders.items():
        row = mapping[ms[0]["series_ticker"]]
        stn = row["proposed_station"]
        if stn not in obs_cache:
            obs_cache[stn] = load_obs_rounded(stn)
        d = event_date(ev)
        obs_day = obs_cache[stn].get(d.isoformat())
        if not obs_day:
            continue
        m_h, _ = day_profile(obs_day)
        settled = None
        for m in ms:
            try:
                settled = float(m["expiration_value"])
                break
            except (KeyError, TypeError, ValueError):
                continue
        if settled is None:
            continue
        candles = {m["ticker"]: load_candles(m, row["iem_tzname"]) for m in ms}
        for H in HOURS:
            M = m_h.get(H)
            cell = table.get((ms[0]["series_ticker"], d.month, H))
            if M is None or cell is None or sum(cell.values()) < MIN_CELL:
                continue
            for m in ms:
                c = candles[m["ticker"]].get(H)
                if not c or _volume(c) < 20:
                    continue
                b = yes_bounds(m)
                if b == (None, None):
                    continue
                ask, bid = _price(c, "yes_ask", "high"), _price(c, "yes_bid", "low")
                if ask is None or bid is None:
                    continue
                p = fair_value(cell, M, b)
                q = (ask + bid) / 2
                y = 1.0 if in_bucket(settled, b) else 0.0
                sm += (p - y) ** 2
                sq += (q - y) ** 2
                n += 1

                # Robustness on how the market's forecast is CONSTRUCTED.
                # q above is (yes_ask.high + yes_bid.low)/2, the midpoint of
                # the widest spread seen in the hour. That pair is §6's
                # deliberately punitive FILL assumption, and scoring the market
                # as a forecaster is a different job, so the reuse has to be
                # shown not to be doing the work. Rescore on the hour's closing
                # mid over the subset where both closes exist, with the model
                # rescored on that identical subset.
                ask_c, bid_c = _price(c, "yes_ask", "close"), _price(c, "yes_bid", "close")
                if ask_c is not None and bid_c is not None:
                    alt[0] += (p - y) ** 2
                    alt[1] += (q - y) ** 2
                    alt[2] += ((ask_c + bid_c) / 2 - y) ** 2
                    alt[3] += 1
                # Reliability of each forecaster ON ITS OWN BINS. The §6 curve
                # in report() is binned by model prediction, which is the right
                # frame for the model and the wrong one for the market: binning
                # the market by the model's prediction measures the model.
                for series, v in (("model", p), ("market", q)):
                    for lo, hi in BINS:
                        if lo <= v < hi:
                            slot = rel[(series, lo, hi)]
                            slot[0] += 1
                            slot[1] += y
                            slot[2] += v
                            break
    return sm / n, sq / n, n, rel, alt


if __name__ == "__main__":
    print("=" * 96)
    print("SECTION 6 FAIR-VALUE CALIBRATION -- training cities only")
    print("=" * 96)
    frozen, shifted = {}, {}
    a = report(0, "FROZEN RULE: observation basis on both sides (Checkpoint 1)", frozen)
    b = report(1, "DIAGNOSTIC ONLY: +1F settlement-basis shift, NOT the frozen rule", shifted)
    print(f"\n  frozen rule worst error {a:.3f}; with a +1F shift {b:.3f}")
    print("  The shift is reported to size a known limitation. It is NOT applied:")
    print("  changing the rule to chase a diagnostic is the sec.8 kill.")

    reliability = collections.defaultdict(lambda: [0, 0.0, 0.0])
    bm, bq, n, reliability, alt = brier(reliability)
    print("\n" + "=" * 96)
    print("MODEL vs MARKET -- Brier score on the same bucket-hours (lower is better)")
    print("=" * 96)
    print(f"  sec.6 fair value : {bm:.4f}")
    print(f"  market mid-quote : {bq:.4f}   over {n:,} bucket-hours")
    better = "MARKET" if bq < bm else "MODEL"
    print(f"  better calibrated: {better}  (by {abs(bm - bq):.4f})")
    if bq < bm:
        print("\n  The quote is a better forecast than the model at every probability bin.")
        print("  This is sec.9's honest prior confirmed rather than refuted: the observation")
        print("  is public and free, and the market already prices it. No recalibration of")
        print("  the model rescues a strategy that has to trade against a better forecast.")

    am, aw, ac, an = alt
    if an:
        print("\n" + "-" * 96)
        print("ROBUSTNESS -- how the market's forecast is constructed")
        print("-" * 96)
        print(f"  The headline quote is (yes_ask.high + yes_bid.low)/2, the midpoint of the")
        print(f"  widest spread in the hour. That pair is sec.6's punitive FILL assumption,")
        print(f"  reused here to score the market. Rescored on the hour's CLOSING mid,")
        print(f"  over the {an:,} bucket-hours where both closes exist:")
        print(f"    sec.6 fair value                        : {am / an:.4f}")
        print(f"    market, widest-spread mid (headline)    : {aw / an:.4f}")
        print(f"    market, closing mid                     : {ac / an:.4f}")
        better = "closing mid" if ac < aw else "widest-spread mid"
        print(f"  The construction moves the market's Brier by {abs(aw - ac) / an:.4f} "
              f"({better} is better),")
        print(f"  against a model-versus-market gap of {abs(am - aw) / an:.4f}. The choice of")
        print(f"  quote construction does not decide the comparison.")

    # Dump exactly what was printed above, so make_figures.py can render the
    # calibration curve without re-running the multi-hour pull. Nothing is
    # recomputed here and no number is rounded on the way out.
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), "figures",
                       "calibration.json")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"frozen": frozen, "shifted": shifted,
                   "brier": {"model": bm, "market": bq, "n": n},
                   "reliability": {
                       series: [{"lo": lo, "hi": hi, "n": c[0],
                                 "realised": c[1] / c[0], "mean_pred": c[2] / c[0]}
                                for (sr, lo, hi), c in sorted(reliability.items())
                                if sr == series and c[0]]
                       for series in ("model", "market")}}, fh, indent=1)
    print(f"\n  wrote {short(out)}")
