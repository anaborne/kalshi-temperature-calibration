"""Step 1, enumerate the universe and pull every settled market.

PREREGISTRATION.md sec.4: the universe is the daily city maximum-temperature
series in Kalshi's "Climate and Weather" category.

  1. GET /series?category=Climate and Weather        -> raw to disk
  2. Select the daily-max-temperature series by an explicit, printed rule.
  3. Walk /markets?series_ticker=..&status=settled for each, paginating on
     `cursor`, writing every page raw to disk before anything is parsed.
  4. Walk /events?series_ticker=..&status=settled as a *coverage census* only.
     See "History horizon" below.
  5. Only then parse the cache into data/parsed/markets.jsonl.

Two tiers, not a ceiling (Correction 1). Kalshi serves settled markets from two tiers with a documented boundary:

    GET /historical/cutoff -> market_settled_ts 2026-06-27T00:00:00Z

Markets settled after that timestamp come from /markets; older ones come from
/historical/markets. An earlier pass of mine took /markets returning nothing for
older events as a hard 68-day ceiling. That was the tiering working, and
asserting the ceiling without checking the other tier was the error.

Measured depth: Aug 2021 through Jun 2026 for the oldest series, all four
seasons, ~9,000 settled city-days across the universe. The events walk is what
enumerates them.

Two things degrade with age and both are handled rather than assumed away:

  - Ladder width. 2021 events carry 1-2 markets, 2022 four, Dec 2022 onward six.
    sec.5's dominated-bucket test is indifferent to width; sec.2's bucket
    recovery gets coarser and that is recorded per event.
  - expiration_value. Populated on recent markets, empty on much of 2021-2024
    and on Nov-Dec 2025. Test A runs its degree-level statistic where the field
    exists and falls back to sec.2 bucket recovery where it does not.

Correction 1 notes that legacy `HIGHNY-*` tickers do not resolve. Measured here,
many of them do, and HIGHNY-22JUL04 returns four markets with a settled value. The
instruction to walk the KX series only is followed regardless, because
/events?series_ticker=KX... already enumerates the legacy-prefixed event tickers
belonging to that series, so nothing is lost by never querying the legacy series
directly. Events that return empty are recorded, not silently dropped.

Selection is deliberately wide. Listing markets is a couple of cheap calls per
series; the expensive pull is step 4. stations.py is the human checkpoint where
the universe gets pruned, per sec.4 ("a silently wrong station produces a
beautiful, entirely fictional edge").

Usage:
    python fetch_markets.py              # resumable; skips series already pulled
    python fetch_markets.py --refresh    # re-pull everything
    python fetch_markets.py --no-census  # skip the /events history census
"""
import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

from common import (DATA, KALSHI, RAW, ensure, get, new_session, parallel_map,
                    read_json, thread_session, write_json, write_raw, short)

CATEGORY = "Climate and Weather"

SERIES_RAW = os.path.join(RAW, "series", "climate_and_weather.json")
MARKETS_RAW = os.path.join(RAW, "markets")
EVENTS_RAW = os.path.join(RAW, "events")
HIST_RAW = os.path.join(RAW, "historical_markets")
UNIVERSE = os.path.join(DATA, "universe.json")
PARSED = os.path.join(DATA, "parsed", "markets.jsonl")
HIST_INDEX = os.path.join(DATA, "historical_index.json")

MONTH_ABBR = ["JAN", "FEB", "MAR", "APR", "MAY", "JUN",
              "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"]

# Frequencies that can carry a per-calendar-day ladder. 'custom' is kept
# because KXPHILHIGH, named in sec.4, is filed under it.
KEEP_FREQ = {"daily", "custom"}

# Title must look like a maximum/high temperature for one place...
TITLE_OK = re.compile(r"\b(high|highest|max|maximum)\b.*\btemp", re.I)
TICKER_OK = re.compile(r"HIGH", re.I)

# ...and must not be one of these, which match the pattern but are not a
# single-station daily max ladder.
TITLE_BAD = re.compile(
    r"\b(low|lowest|min|minimum|average|avg|hourly|weekly|monthly|annual|water|snow|rain)\b",
    re.I,
)

# Matches the pattern but is not a per-city daily bucket ladder.
EXCLUDE = {
    "HIGHUS": "aggregate across cities, not a single station",
    "KXHIGHUS": "aggregate across cities, not a single station",
    "KXMAXTEMP100": "threshold novelty market, not a city ladder",
    "KXHOLIDAYTMAX": "single-date cross-city threshold event, no 2F bucket ladder",
}


def select_universe(series):
    kept, dropped = [], []
    for s in series:
        t = s.get("ticker", "")
        title = s.get("title", "") or ""
        freq = s.get("frequency", "")
        if t in EXCLUDE:
            reason = EXCLUDE[t]
        elif freq not in KEEP_FREQ:
            reason = f"frequency={freq!r}"
        elif TITLE_BAD.search(title):
            reason = "title names a non-max quantity"
        elif not (TITLE_OK.search(title) or TICKER_OK.search(t)):
            reason = "not a high/max temperature series"
        else:
            kept.append(s)
            continue
        dropped.append({"ticker": t, "frequency": freq, "title": title, "reason": reason})
    kept.sort(key=lambda s: s["ticker"])
    return kept, dropped


def fetch_series(session, refresh):
    if os.path.exists(SERIES_RAW) and not refresh:
        print(f"  cached: {short(SERIES_RAW)}")
    else:
        r = get(session, KALSHI + "/series", params={"category": CATEGORY})
        write_raw(SERIES_RAW, r.text)
        print(f"  wrote {short(SERIES_RAW)} ({len(r.text):,} bytes)")
    return read_json(SERIES_RAW).get("series", [])


def _clear(outdir):
    ensure(outdir)
    for stale in os.listdir(outdir):
        if stale.startswith("page_") or stale == "_complete.json":
            os.remove(os.path.join(outdir, stale))


def _paginate(session, outdir, url, params, key, refresh, max_pages=500):
    """Walk a cursor-paginated endpoint, writing each page raw before parsing."""
    done = os.path.join(outdir, "_complete.json")
    if os.path.exists(done) and not refresh:
        d = read_json(done)
        return d["pages"], d["count"], True

    _clear(outdir)
    page, count, cursor = 0, 0, None
    params = dict(params)
    while True:
        if cursor:
            params["cursor"] = cursor
        r = get(session, url, params=params)
        write_raw(os.path.join(outdir, f"page_{page:04d}.json"), r.text)
        body = json.loads(r.text)
        items = body.get(key) or []
        count += len(items)
        page += 1
        cursor = body.get("cursor")
        if not cursor or not items:
            break
        if page >= max_pages:
            raise RuntimeError(f"pagination did not terminate: {url} {params}")
    write_json(done, {"url": url, "params": params, "pages": page, "count": count})
    return page, count, False


def pull_markets(session, ticker, refresh):
    return _paginate(
        session, os.path.join(MARKETS_RAW, ticker), KALSHI + "/markets",
        {"series_ticker": ticker, "status": "settled", "limit": 1000},
        "markets", refresh,
    )


def pull_events(session, ticker, refresh):
    return _paginate(
        session, os.path.join(EVENTS_RAW, ticker), KALSHI + "/events",
        {"series_ticker": ticker, "status": "settled", "limit": 200},
        "events", refresh, max_pages=200,
    )


def _pages(outdir):
    if not os.path.isdir(outdir):
        return
    for name in sorted(os.listdir(outdir)):
        if name.startswith("page_"):
            yield read_json(os.path.join(outdir, name))


def parse_cache(tickers):
    """Parse both tiers off disk into one flat JSONL. No network.

    `tier` is stamped on every row so downstream code can tell which endpoint a
    market came from without re-deriving it from timestamps.
    """
    ensure(os.path.dirname(PARSED))
    n = collections.Counter()
    seen = set()
    with open(PARSED, "w", encoding="utf-8") as out:
        for ticker in tickers:
            rows = []
            for body in _pages(os.path.join(MARKETS_RAW, ticker)):
                for m in body.get("markets") or []:
                    rows.append(("live", m))
            hist = os.path.join(HIST_RAW, ticker)
            if os.path.isdir(hist):
                for name in sorted(os.listdir(hist)):
                    if not name.endswith(".json"):
                        continue
                    try:
                        body = read_json(os.path.join(hist, name))
                    except ValueError:
                        continue
                    for m in body.get("markets") or []:
                        rows.append(("historical", m))
            for tier, m in rows:
                if m["ticker"] in seen:
                    continue
                seen.add(m["ticker"])
                m["series_ticker"] = ticker
                m["tier"] = tier
                out.write(json.dumps(m, sort_keys=True) + "\n")
                n[tier] += 1
    return n


def parse_event_date(event_ticker):
    """'KXHIGHNY-26AUG25' / 'HIGHNY-21AUG06' -> date. None if it is not a day."""
    suffix = event_ticker.rsplit("-", 1)[-1]
    try:
        yy, mon, dd = suffix[:2], suffix[2:5], suffix[5:]
        return dt.date(2000 + int(yy), MONTH_ABBR.index(mon) + 1, int(dd))
    except (ValueError, IndexError):
        return None


def known_events(ticker):
    """date -> event_ticker, from the events census and the live markets pull."""
    found = {}
    for body in _pages(os.path.join(EVENTS_RAW, ticker)):
        for e in body.get("events") or []:
            d = parse_event_date(e["event_ticker"])
            if d:
                found[d] = e["event_ticker"]
    for body in _pages(os.path.join(MARKETS_RAW, ticker)):
        for m in body.get("markets") or []:
            d = parse_event_date(m["event_ticker"])
            if d:
                found[d] = m["event_ticker"]
    return found


def candidate_events(ticker):
    """Every event ticker worth trying, one per calendar day in the span.

    The census and the live pull between them leave interior gaps, because
    /events stops short of the live tier's oldest markets. Those days are filled by
    generating the modern KX-prefixed ticker, which is uniform across the
    universe. A generated ticker that returns nothing is recorded as empty
    rather than dropped, so the gap stays visible.
    """
    found = known_events(ticker)
    if not found:
        return [], {}
    lo, hi = min(found), max(found)
    out, generated = [], {}
    day = lo
    while day <= hi:
        if day in found:
            out.append(found[day])
        else:
            gen = f"{ticker}-{day.year % 100:02d}{MONTH_ABBR[day.month - 1]}{day.day:02d}"
            out.append(gen)
            generated[gen] = True
        day += dt.timedelta(days=1)
    return out, generated


def live_event_tickers(ticker):
    have = set()
    for body in _pages(os.path.join(MARKETS_RAW, ticker)):
        for m in body.get("markets") or []:
            have.add(m["event_ticker"])
    return have


def pull_historical(session, ticker, refresh, on_progress=None):
    """One /historical/markets call per settled day not already served live."""
    events, _ = candidate_events(ticker)
    live = live_event_tickers(ticker)
    outdir = os.path.join(HIST_RAW, ticker)
    ensure(outdir)
    todo = [ev for ev in events if ev not in live]
    stats = collections.Counter()

    def one(ev):
        path = os.path.join(outdir, ev + ".json")
        if os.path.exists(path) and not refresh:
            return path, True
        r = get(thread_session(), KALSHI + "/historical/markets",
                params={"event_ticker": ev, "limit": 200})
        write_raw(path, r.text)
        return path, False

    def collect(i, ev, value, error):
        if error is not None:
            stats["error"] += 1
            print(f"    !! {ev}: {error}")
            return
        path, cached = value
        stats["cached" if cached else "fetched"] += 1
        try:
            ms = read_json(path).get("markets") or []
        except ValueError:
            ms = []
        if ms:
            stats["historical_markets"] += len(ms)
        else:
            stats["empty"] += 1
        if on_progress:
            on_progress(stats)

    parallel_map(one, todo, on_result=collect)
    return {"candidates": len(events), "live": len(live & set(events)),
            "fetched": stats["fetched"], "cached": stats["cached"],
            "empty": stats["empty"], "errors": stats["error"],
            "historical_markets": stats["historical_markets"]}


def event_span(ticker):
    """(count, oldest, newest) settled event tickers seen in the census."""
    evs = set()
    for body in _pages(os.path.join(EVENTS_RAW, ticker)):
        for e in body.get("events") or []:
            evs.add(e["event_ticker"])
    if not evs:
        return 0, None, None
    s = sorted(evs)
    return len(evs), s[0], s[-1]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="ignore cache and re-pull")
    ap.add_argument("--no-census", action="store_true", help="skip the /events history census")
    ap.add_argument("--no-historical", action="store_true",
                    help="skip the /historical/markets deep pull")
    args = ap.parse_args()

    session = new_session()

    print("== series listing ==")
    series = fetch_series(session, args.refresh)
    print(f"  {len(series)} series in category {CATEGORY!r}")

    kept, dropped = select_universe(series)
    print(f"\n== universe selection: {len(kept)} kept, {len(dropped)} dropped ==")

    fees = sorted({(s.get("fee_type"), s.get("fee_multiplier")) for s in kept})
    print(f"  live fee terms across universe (fee_type, fee_multiplier): {fees}")
    if fees != [("quadratic", 1)]:
        print("  !! non-default fee terms present -- test_b.py must key fees per series")

    print(f"\n== settled pull ({len(kept)} series) ==")
    print(f"  {'series':<16} {'mkts':>7} {'events':>7}  {'oldest':<20} {'newest':<20} fee")
    rows = []
    for i, s in enumerate(kept, 1):
        t = s["ticker"]
        _, n_mkt, _ = pull_markets(session, t, args.refresh)
        if args.no_census:
            n_ev = oldest = newest = None
        else:
            pull_events(session, t, args.refresh)
            n_ev, oldest, newest = event_span(t)
        rows.append({
            "series_ticker": t, "title": s.get("title"), "frequency": s.get("frequency"),
            "fee_type": s.get("fee_type"), "fee_multiplier": s.get("fee_multiplier"),
            "settled_markets": n_mkt, "settled_events": n_ev,
            "oldest_settled_event": oldest, "newest_settled_event": newest,
        })
        print(f"  {t:<16} {n_mkt:>7,} {(n_ev if n_ev is not None else -1):>7,}  "
              f"{str(oldest):<20} {str(newest):<20} {s.get('fee_multiplier')}")
        sys.stdout.flush()

    live = [r for r in rows if r["settled_markets"] > 0]
    print(f"\n  {len(live)} series carry retrievable settled markets; "
          f"{len(rows) - len(live)} are empty (unlaunched, retired, or outside the window)")
    print(f"  total settled markets: {sum(r['settled_markets'] for r in rows):,}")
    if not args.no_census:
        gap = sum(r["settled_events"] or 0 for r in rows)
        print(f"  total settled event-days the exchange has ever run: {gap:,}")
        print("  -> market-level detail is only retrievable for the recent window; "
              "the rest is a hard sample-size ceiling, not a bug in this script")

    write_json(UNIVERSE, {
        "category": CATEGORY,
        "selection_rule": {
            "keep_frequency": sorted(KEEP_FREQ),
            "title_must_match": TITLE_OK.pattern,
            "or_ticker_must_match": TICKER_OK.pattern,
            "title_must_not_match": TITLE_BAD.pattern,
            "excluded_by_name": EXCLUDE,
        },
        "series": rows,
        "dropped": dropped,
        "raw": {"series": SERIES_RAW, "markets": MARKETS_RAW, "events": EVENTS_RAW},
    })
    print(f"\n  wrote {short(UNIVERSE)}")

    if not args.no_historical:
        print(f"\n== historical tier pull (Correction 1) ==")
        r = get(session, KALSHI + "/historical/cutoff")
        cutoff = json.loads(r.text)
        print(f"  cutoff market_settled_ts = {cutoff.get('market_settled_ts')}")
        print(f"  {'series':<16} {'days':>6} {'live':>6} {'pulled':>7} {'cached':>7} "
              f"{'empty':>6} {'markets':>8}  ({os.environ.get('TV_WORKERS','1')} workers, "
              f"{os.environ.get('TV_RATE') or '1/'+os.environ.get('TV_MIN_INTERVAL','0.30')} rps)")
        hist = {}
        for i, s in enumerate(live, 1):
            t = s["series_ticker"]
            st = pull_historical(session, t, args.refresh)
            hist[t] = st
            print(f"  {t:<16} {st['candidates']:>6,} {st['live']:>6,} {st['fetched']:>7,} "
                  f"{st['cached']:>7,} {st['empty']:>6,} {st['historical_markets']:>8,}")
            sys.stdout.flush()
        write_json(HIST_INDEX, {"cutoff": cutoff, "series": hist})
        print(f"  wrote {short(HIST_INDEX)}")

    print("\n== parsing cache ==")
    n = parse_cache([s["ticker"] for s in kept])
    print(f"  wrote {short(PARSED)} ({sum(n.values()):,} rows: {dict(n)})")


if __name__ == "__main__":
    main()
