# How this project handles claims

Two things live here. What I have verified against a primary source, with the
date I verified it, and the convention this repository follows when something I
wrote turns out to be wrong. The test itself is described in
[`README.md`](README.md), the binding spec is
[`PREREGISTRATION.md`](PREREGISTRATION.md), and the measurements are in
[`RESULTS.md`](RESULTS.md).

## Corrections

I append corrections and never edit one in place. A correction gets its own
dated section, states plainly what the earlier text got wrong, and leaves the
wrong text standing above it. `PREREGISTRATION.md` carries four numbered ones
and three dated notes inside them, all retracting my own earlier reasoning, and
`RESULTS.md` carries eleven dated ones. The error trail is part of the record,
so nothing here is quietly revised into looking better than it was.

## The failure that produced this

On 2026-08-27 an early pass of this work reported that Kalshi's `/markets`
endpoint returns only a rolling ~68-day window. That was true.

I then "verified" it by querying one older event, getting an empty array, and
writing into the Stage 3 pre-registration: *"There is no paid tier that fixes
this and no archive to fall back on."*

That sentence had no evidence behind it. I had run no search. It was false.
Kalshi serves a full `/historical/*` tier, unauthenticated, back at least 19
months. The claim went into git, and had it stood it would have silently capped
the study's sample at 68 summer days instead of the 1,843 dates it eventually
covered. The check I skipped cost one web search.

Correction 1 in [`PREREGISTRATION.md`](PREREGISTRATION.md) records the
retraction, and the false sentence is still there, above it, unedited.

## What I verified about the Kalshi API

Each item was verified against a primary source, cited inline, and carries the
date and the method of verification.

### Kalshi API, verified 2026-08-27, unauthenticated

- Settlement authority is whatever the market's own `rules_primary` names. The
  help centre is stale and is not binding.
- Daily temperature markets switched settlement authority around 2026-08-13,
  from the NWS Climatological Report (Daily) to The Weather Company, across 20
  of 21 city series. Both regimes appear in any sample spanning that date, and
  an analysis that does not stratify on it is pooling two regimes.
- `/markets` serves a live tier only. Anything settled before the timestamp at
  `GET /historical/cutoff` (2026-06-27 as of this date) is served by
  `/historical/markets`, `/historical/markets/{ticker}`, and
  `/historical/markets/{ticker}/candlesticks`. The historical candlesticks path
  takes no series segment, unlike the live one. Verified back to January 2025.
- `expiration_value` gives the exact settled value on recent markets and is
  absent on older ones. The settled ladder recovers the bucket in either case.
- Legacy series prefixes resolve for some dates and not others.
  `HIGHNY-25JAN15` returns empty; `HIGHNY-22JUL04` returns four settled markets.
  The archive is not truncated at the KX rename.
  *Corrected 2026-08-27: an earlier ledger entry read "legacy prefixes do not
  resolve", generalised from a single empty ticker. That is the same mistake as
  the one above, made by me a second time, four hours after I wrote down the
  check against it.*
  Walking `KX` series still suffices in practice, because
  `/events?series_ticker=KX…` enumerates the legacy-prefixed event tickers
  anyway. The archive does not stop at the rename and must not be described as
  if it does.
- Kalshi station identifiers are quoted in the rules text and are not always the
  obvious airport. Chicago is CLIMDW (Midway, not O'Hare), Houston is CLIHOU
  (Hobby, not Bush). A wrong airport manufactures a clean, entirely fictional
  edge, which is why [`stations.py`](stations.py) halts for a human to read the
  mapping table before anything downstream runs.
- Fees, schedule effective 2026-07-07: taker `roundup(M × 0.07 × C × P × (1−P))`,
  M defaults to 1; maker `roundup(M × 0.0175 × C × P × (1−P))`, M defaults to 0;
  no settlement fee. I confirmed the per-series multiplier against the live
  schedule, because on a strategy this thin the fee term is not a detail.

### Data handling

- Numbers that a language model transcribed do not go into a backtest. Some
  exploratory reads during design came back through a summarising fetch proxy,
  which is fine for reading six markets and disqualifying for a measurement.
  Every number in [`RESULTS.md`](RESULTS.md) comes from a raw API response
  written to disk unmodified, then parsed by committed code.
- Raw responses land on disk before anything parses them, so every downstream
  result is reproducible from cache without re-pulling.
