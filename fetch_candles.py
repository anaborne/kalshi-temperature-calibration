"""Step 4, pull hourly candlesticks for every settled market.

PREREGISTRATION.md sec.3: GET /series/{s}/markets/{t}/candlesticks?period_interval=60
carries separate `yes_bid` and `yes_ask` OHLC plus volume and open interest.
That separation is the point. sec.6 fills at yes_ask.high or yes_bid.low, the
worst quote in the hour, which is only possible with two-sided candles. Filling
against a last trade is the standard way this class of backtest lies to itself.

Two endpoints, picked per market (Correction 1). Markets settled after
/historical/cutoff are served live:

    /series/{series}/markets/{ticker}/candlesticks

and older ones by the historical tier, whose path takes NO series segment:

    /historical/markets/{ticker}/candlesticks

Getting that wrong is a silent 404 per market, which would look exactly like a
market that never traded. The tier stamped on each row by fetch_markets.py is
what selects the endpoint, so the choice is data-driven rather than inferred
from a timestamp comparison here.

This is the long pull: ~50,000 markets across five years, one call each.
Resumable by design. One file per market, a market with a file on disk is
skipped, and the process can be killed and restarted at any point. Concurrency
is bounded and the request rate is shared across workers; measured on this API,
6 rps runs clean and 12 rps earns 429s and is net slower.

Holdout note. This fetches holdout markets too. sec.7 forbids loading, plotting
or summarising the holdout until the Test B rule is frozen; it does not forbid
caching bytes that nothing reads. test_b.py is where that discipline is
enforced, and it enforces it in code rather than by convention.

Usage:
    python fetch_candles.py                 # resumable
    python fetch_candles.py --series KXHIGHNY
    python fetch_candles.py --status        # what is cached, pull nothing
"""
import argparse
import collections
import datetime as dt
import json
import os
import sys

from common import (DATA, KALSHI, RAW, get, parallel_map, read_json,
                    thread_session, write_raw, short)

MARKETS = os.path.join(DATA, "parsed", "markets.jsonl")
CANDLES_RAW = os.path.join(RAW, "candles")

# Candles are requested over a window bracketing the trading day. Markets open
# ~2 days before close, so reach back 4 days and forward 1 to be safe: the API
# clips to what exists and an over-wide window costs nothing.
LOOKBACK_DAYS = 4
LOOKAHEAD_DAYS = 1


def load_markets(series_filter=None):
    if not os.path.exists(MARKETS):
        sys.exit(f"missing {MARKETS} -- run fetch_markets.py first")
    out = []
    for line in open(MARKETS, encoding="utf-8"):
        m = json.loads(line)
        if series_filter and m["series_ticker"] != series_filter:
            continue
        out.append(m)
    return out


def path_for(m):
    return os.path.join(CANDLES_RAW, m["series_ticker"], m["ticker"] + ".json")


def window(m):
    """(start_ts, end_ts) in unix seconds, bracketing this market's life."""
    close = dt.datetime.fromisoformat(m["close_time"].replace("Z", "+00:00"))
    start = close - dt.timedelta(days=LOOKBACK_DAYS)
    end = close + dt.timedelta(days=LOOKAHEAD_DAYS)
    return int(start.timestamp()), int(end.timestamp())


def candles_urls(m):
    """Both tier paths, most-likely first.

    The tier stamp records which LISTING endpoint returned the market, and that
    is not always the tier that serves its candlesticks. 84 markets settled
    2026-06-20, a week before the /historical/cutoff of 2026-06-27, are
    returned by the live /markets listing but 404 on the live candlestick path
    and resolve on the historical one. So the stamp orders the attempt and the
    other path is the fallback, rather than the stamp being trusted absolutely.
    """
    live = f"{KALSHI}/series/{m['series_ticker']}/markets/{m['ticker']}/candlesticks"
    hist = f"{KALSHI}/historical/markets/{m['ticker']}/candlesticks"
    return [hist, live] if m.get("tier") == "historical" else [live, hist]


def pull(m):
    path = path_for(m)
    if os.path.exists(path):
        return True, None
    a, b = window(m)
    params = {"period_interval": 60, "start_ts": a, "end_ts": b}
    last = None
    for url in candles_urls(m):
        try:
            r = get(thread_session(), url, params=params, tries=3)
        except Exception as exc:                            # noqa: BLE001
            last = exc
            continue
        write_raw(path, r.text)
        return False, json.loads(r.text)
    raise last


def count_cached(markets):
    have = sum(1 for m in markets if os.path.exists(path_for(m)))
    return have, len(markets)


def candle_count(m):
    p = path_for(m)
    if not os.path.exists(p):
        return None
    try:
        return len(read_json(p).get("candlesticks") or [])
    except (ValueError, OSError):
        return -1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--series", help="one series only")
    ap.add_argument("--status", action="store_true", help="report cache state, pull nothing")
    args = ap.parse_args()

    markets = load_markets(args.series)
    have, total = count_cached(markets)

    if args.status:
        print(f"== candlestick cache: {have:,}/{total:,} markets ==")
        by = {}
        for m in markets:
            s = by.setdefault(m["series_ticker"], [0, 0, 0])
            s[1] += 1
            n = candle_count(m)
            if n is not None:
                s[0] += 1
                s[2] += max(n, 0)
        for s in sorted(by):
            got, tot, candles = by[s]
            print(f"  {s:<14} {got:>5,}/{tot:<5,} markets  {candles:>8,} candles"
                  f"{'  EMPTY' if got and not candles else ''}")
        return

    tiers = collections.Counter(m.get("tier", "live") for m in markets)
    print(f"== candlestick pull: {total - have:,} to fetch, {have:,} cached, tiers {dict(tiers)} ==")
    started = dt.datetime.now()
    state = collections.Counter()
    todo = [m for m in markets if not os.path.exists(path_for(m))]

    def collect(i, m, value, error):
        state["done"] += 1
        if error is not None:
            state["error"] += 1
            if state["error"] <= 20:
                print(f"  !! {m['ticker']}: {error}")
            return
        cached, body = value
        if not cached:
            state["fetched"] += 1
            if not (body.get("candlesticks") or []):
                state["empty"] += 1
        if state["done"] % 500 == 0:
            secs = (dt.datetime.now() - started).total_seconds()
            rate = state["fetched"] / secs if secs and state["fetched"] else 0
            left = (len(todo) - state["done"]) / rate / 60 if rate else 0
            print(f"  [{state['done']:>6,}/{len(todo):,}] fetched={state['fetched']:,} "
                  f"empty={state['empty']:,} err={state['error']:,} "
                  f"{rate:.1f}/s  ~{left:.0f} min left")
            sys.stdout.flush()

    parallel_map(pull, todo, on_result=collect)
    empty = state["empty"]
    if state["error"]:
        print(f"  {state['error']:,} markets errored; rerun to retry (nothing was written "
              f"for them, so they are simply still missing)")

    have, total = count_cached(markets)
    print(f"\n  cached {have:,}/{total:,} markets under {short(CANDLES_RAW)}/")
    if empty:
        print(f"  {empty:,} markets returned zero candles -- these never traded "
              f"and are simply untradeable in the backtest, not an error")


if __name__ == "__main__":
    main()
