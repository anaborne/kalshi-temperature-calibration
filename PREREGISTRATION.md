# Stage 3 offline backtest, pre-registration

Written 2026-08-27, before any backtest data has been pulled. That ordering is the point. Charter §4 requires the test be decided before it is run and the holdout untouched; this document is that decision, timestamped, so it cannot be quietly rewritten after the numbers come back.

Candidate under test: C3, weather settlement convergence. It is the only candidate in Stage 3.

Everything below cost $0 and used unauthenticated public endpoints.

---

> **Two notes for a reader outside the project.**
>
> **"The charter"** is a private planning doc governing this work. Only two of
> its sections are load-bearing here, and both are stated in full so nothing
> below depends on a document you cannot read. §3 sets the research budget at
> $0, and paid data does not unlock until a candidate has provisionally survived
> Stage 3. §4 says a test is decided in writing before it is run, the holdout is
> untouched until the rule is frozen, and a strategy that needs parameter tuning
> to work is dead. The candidate log and the Stage 1-2 write-ups referenced in
> passing are part of the same private material and are not required to follow
> the argument.
>
> **Redactions, 2026-08-27.** Before this repository was made public, six
> passages naming the author's personal circumstances, private filenames, or
> unrelated repositories were replaced with public equivalents. In full:
>
> | where | was | is |
> |---|---|---|
> | title | the private filename | `Stage 3` |
> | §1 | a private filename | "the programme's candidate log" |
> | §8 | what the research hours compete with | "other commitments" |
> | §9 | what the work must serve besides the venture | "something publishable as well as something tradeable" |
> | §10 ¶1 | the specific machines with no network egress | "the environment this document was drafted in" |
> | §10 ¶3 | the operator's machine and an unrelated repository | a statement that it runs with direct network access |
>
> No test parameter, threshold, cell key, kill criterion, finding or correction
> was altered. The redactions touch motivation, filenames and hardware, and
> never the spec. Everything else stands exactly as committed on 2026-08-27,
> including every sentence later corrected, since corrections here are appended
> and never edited in place.

---

## 1. The blocking item is resolved: The Weather Company governs

Stage 2 left one item that blocked everything else, whether KXHIGHNY settles on the NWS Daily Climate Report (help centre) or The Weather Company (`rules_primary`). Resolved in favour of `rules_primary`, on the operating rule that binding market rules govern and help-centre prose is not binding.

Read live from `GET /markets?event_ticker=KXHIGHNY-26AUG25` on 2026-08-27, the whole ladder agrees:

> "If the maximum temperature recorded at New York City (CLINYC) for Aug 25, 2026, is greater than 86° fahrenheit according to The Weather Company, then the market resolves to Yes."

Same clause on the `less`, `between` and `greater` variants. Not a one-market typo.

The help centre is stale. That is now a fact about Kalshi's documentation, and it stands as a live instance in the programme's candidate log.

**Consequence that mattered less than expected.** Stage 2 assumed that if TWC governs, C3 needs paid TWC data. It does not, because of §2.

---

## 2. Settled results are free ground truth for the only quantity that pays

A city-day's ladder is six markets. Aug 25 NY, actual:

| Ticker | Type | Range | Result | Volume |
|---|---|---|---|---|
| T79 | less | < 79 | yes | 43,499 |
| B79.5 | between | 79-80 | no | 42,195 |
| B81.5 | between | 81-82 | no | 21,047 |
| B83.5 | between | 83-84 | no | 1,752 |
| B85.5 | between | 85-86 | no | 1,231 |
| T86 | greater | > 86 | no | 1,314 |

Buckets are 2°F wide with open-ended tails. The yes/no pattern therefore does not recover TWC's exact number. It recovers which bucket TWC's number fell in.

That is sufficient, and it is worth being precise about why. The strategy never gets paid on TWC's exact value. It gets paid on which bucket settles. A disagreement between a free observation feed and TWC costs money only when it flips the bucket, and a bucket flip is exactly what the settled ladder makes visible. I am blind only to within-bucket disagreements, which by construction pay nothing.

So the Stage 2 second-order question, "how tightly does free METAR track TWC", gets replaced by a sharper and cheaper one. How often does a free-observation-derived running maximum imply a bucket that the settled ladder contradicts. No TWC subscription, no paid data, no charter §3 unlock needed.

---

## 3. Data sources, both confirmed live and both free

**Market side.** `GET /series/{series}/markets/{ticker}/candlesticks?period_interval=60`, hourly, unauthenticated, with separate `yes_bid` and `yes_ask` OHLC series plus volume and open interest. Confirmed in Stage 2. This is what lets the backtest fill against a price that existed. Filling against a last trade is the standard way this class of backtest lies to itself.

**Observation side.** Iowa Environmental Mesonet ASOS archive. Confirmed live today:

`https://mesonet.agron.iastate.edu/cgi-bin/request/asos.py?station=NYC&data=tmpf&year1=..&tz=America/New_York&format=onlycomma&report_type=3,4`

returns

```
station,valid,tmpf
NYC,2026-08-24 00:51,70.00
NYC,2026-08-24 01:51,69.00
...
```

Unauthenticated CSV, timezone-aware, decades of history, whole-degree °F at NYC. `report_type=3,4` to include specials as well as routine hourlies, since a spike that only appears in a SPECI still counts toward the day's maximum.

Neither source costs anything and neither needs a key. Charter §3 research budget stays at $0.

---

## 4. Universe

`GET /series?category=Climate and Weather` returns roughly 20 daily city maximum-temperature series, among them `KXHIGHNY`, `KXHIGHCHI`, `KXHIGHMIA`, `KXHIGHTBOS`, `KXHIGHTPHX`, `KXHIGHTSEA`, `KXHIGHTDC`, `KXHIGHTDAL`, `KXHIGHTHOU`, `KXHIGHTEWR`, `KXHIGHTNOLA`, `KXHIGHTOKC`, `KXHIGHTSATX`, `KXHIGHTSAN`, `KXPHILHIGH`.

This matters twice. It is the sample-size multiplier, and it is what makes an honest holdout possible (§7).

**Station mapping is a manual checkpoint.** The pipeline parses the station named in each series' `rules_primary` and proposes an ASOS identifier. `CLINYC → NYC` is confirmed. Every other mapping gets printed as a table and read by a human before the pull runs. A silently wrong station produces a beautiful, entirely fictional edge.

---

## 5. Test A, the safety test. Model-free, and it gates everything

**Question.** Is a running maximum built from free observations a genuine floor under the settled bucket?

**Construction.** For each settled city-day, for each local hour H from 09:00 to 23:00: let `M_H` = the maximum `tmpf` observed from 00:00 local through H. A bucket is *dominated at H* if its entire range lies strictly below `M_H`. A dominated bucket must settle No, because the day's maximum is monotone non-decreasing in H and can only end at or above `M_H`.

**Measure.** Over all (city-day, bucket, H) triples, the count and rate of dominated buckets that nonetheless settled Yes. Every such case is a place where TWC's value came in below the free feed's already-observed reading.

**Rounding.** METAR is reported in whole °F at NYC but some stations arrive as Celsius conversions with decimals. Compute both a round-half-up-to-integer variant and an unrounded variant. If they disagree on any Test A outcome, report both and treat the pessimistic one as the result.

**Pre-committed interpretation.**

| Violation rate | Verdict |
|---|---|
| 0 over n ≥ 5,000 dominated-bucket-hours | Floor is safe to a rule-of-three upper bound of 3/n. Proceed to Test B. |
| > 0 but < 0.5% | Floor leaks. Proceed to Test B only with the measured leak rate priced into every trade as a loss term. |
| ≥ 0.5% | TWC diverges downward from free observations materially. C3 dies at Stage 3. Paid TWC data is not the escape hatch, because charter §3 does not unlock it until after provisional Stage 3 survival, and this *is* Stage 3. |

Test A is worth running on its own merits. Whatever it says, it is a measured public statement about whether a $100k-a-day-per-city market settles where free public data says it should, which is the artifact half of this candidate's justification.

---

## 6. Test B, the actual strategy

Test A only says a floor exists. It does not say anyone is paying for it. The money, if there is any, is in the bucket that *contains* `M_H` still trading below fair because the market is carrying forecast uncertainty that the afternoon already resolved.

**One estimated input, and it is a lookup table.** Residual warming `R = (final daily max) − M_H`. Estimated as a plain empirical frequency table keyed by (local hour H, calendar month, city), from training cities only, no smoothing, no functional form, no free parameters. A cell with fewer than 200 observations is not traded. Charter §4: a strategy that needs parameter tuning to work is dead, so there is nothing here to tune.

**Fair value.** At hour H, probability that bucket b settles Yes = empirical frequency of `M_H + R` landing in b.

**Entry rule, frozen now.**
- Trade when `|fair − quote|` ≥ 10¢ after fees.
- Buy at that hour's `yes_ask.high`, sell at that hour's `yes_bid.low`, the worst quote in the hour. Only hourly OHLC is available, with no depth, so the fill assumption is deliberately punitive.
- Size capped at the lesser of 5% of that hour's volume and $25 notional.
- One position per city-day-hour. Hold to settlement. No exits, because exits are where discretion re-enters.

**Fees.** From the Kalshi fee schedule effective 2026-07-07:

```
taker: fees = roundup(M × 0.07 × C × P × (1-P)),  M defaults to 1
maker: fees = roundup(M × 0.0175 × C × P × (1-P)), M defaults to 0
       rounded up so that fee + positionCost lands on a centicent
       no settlement fee
```

Assume taker on every fill; assume no maker rebate. The pipeline must confirm the per-series multiplier for weather markets, because on a strategy this thin the fee term is not a detail.

Worth stating plainly what the fee curve does to the two shapes available:

- **Selling a dominated 2¢ bucket:** fee 0.14¢/contract, net 1.86¢ won against 98.14¢ risked. Breakeven accuracy 98.1%. This is picking up pennies and its entire EV lives in the tail-error rate, which is precisely why Test A gates it.
- **Buying a 70¢ bucket worth 90¢:** fee 1.47¢/contract, 18.5¢ net edge. This is the trade worth having.

If the backtest's PnL turns out to come mostly from the first shape, treat that as a red flag.

---

## 7. Split, and why it is by city

Weather is seasonal and Kalshi's weather listings are young, so a chronological 70/30 split confounds season with regime and produces a holdout that is testing August against November. Split by city instead, same date range on both sides.

Assignment, fixed now, before the pull, by `md5(series_ticker)` low bit (even to train, odd to holdout) with the resulting table printed and pasted into this document at pull time and never revised. Target roughly 70/30 by city-day count; if the hash lands worse than 60/40, take the printed assignment anyway. Reseeding to taste is holdout leakage wearing a lab coat.

The holdout is not loaded, plotted, or summarised until the rule is frozen. It is run once.

---

## 8. Kill criteria, committed before capital or further hours

- Test A violation rate ≥ 0.5% → C3 dies.
- Fewer than 30 qualifying trades in holdout → no conclusion. Do not lower the 10¢ threshold to manufacture trades. Report the null and stop.
- Holdout mean PnL per trade, 95% bootstrap CI, lower bound ≤ 0 → C3 dies.
- Realised net edge < 3¢/contract → park it. It clears zero but not the hours, and the hours compete with other commitments.
- Any change to threshold, cell keys, fill assumption or split *after* the holdout is seen → C3 dies. That is the specific self-deception charter §4 names.

---

## 9. Honest prior

The likeliest outcome is that late-afternoon quotes already track observed readings, because the observation is public and free and this is the obvious thing to do with it. Stage 2 asked this question and did not answer it. The expected result is a small edge in a narrow hour band, or none.

Two things make it worth running anyway: it is cheap, and Test A produces a publishable measurement whether or not the trade exists. Per the charter's standing flag, if this stops producing something publishable as well as something tradeable, cut it.

---

## 10. Where this has to run

The environment this document was drafted in has no network egress to `api.elections.kalshi.com`, `aviationweather.gov` or `ncei.noaa.gov`, re-confirmed today. The only path available there is a fetch proxy that returns one URL at a time and paraphrases the JSON through a summarising language model. Every JSON quoted in this document came back that way. That is fine for reading six markets and disqualifying for a backtest, because a strategy must not be tested against numbers that were transcribed by a language model. Nothing quoted above is treated as data, and the pipeline re-pulls all of it.

Scale of the pull: ~20 series × ~6 markets/day × however many settled days exist, each needing a candlestick call, on the order of 10⁴ requests, plus 20 bulk ASOS CSVs, producing ~10⁵ hourly rows. That is a terminal job.

So it runs in a terminal with direct network access, with raw responses written to disk before anything parses them. It lives in a fresh git repository, since Test A's output is meant to be publishable.

---

# Checkpoint 1, station mapping and pre-pull findings

Recorded 2026-08-27 after steps 1-2 of the pipeline. I re-verified every item below against the live API in a separate pass before accepting it.

## Station mapping: accepted

21 series, each corroborated by a `CLIxxx` code quoted inside its own rules text. Two are not the obvious airport and both were verified directly:

- `KXHIGHCHI → MDW`. Rules say CLIMDW, Midway, not O'Hare. Chicago's official climate site is ORD, so the obvious mapping is the wrong one.
- `KXHIGHTHOU → HOU`. Rules say CLIHOU, Hobby, not Bush. The pipeline initially proposed IAH on the reasonable ground that Kalshi lists Hobby separately as `KXHOBBYTEMP`. IAH runs +0.38 °F above settlement; HOU runs −0.82 °F below, in line with the other eleven cities checked. An IAH mapping would have manufactured floor violations out of nothing but a wrong airport. This is the checkpoint from §4 paying for itself on its first use.

## The settlement authority changed mid-sample

Verified by direct read of two NY markets:

| Date | rules_primary |
|---|---|
| 2026-07-23 | "the highest temperature recorded in Central Park, New York ... as reported by the National Weather Service's Climatological Report (Daily)" |
| 2026-08-25 | "the maximum temperature recorded at New York City (CLINYC) ... according to The Weather Company" |

Aug 12 is still NWS, Aug 18 is already TWC. The switch lands between them and covers 20 of 21 series. So §1's live read was correct about *today* and incomplete about the *sample*: roughly 18% of the available window settles on TWC, the remaining 82% on NWS CLI.

**Decision.** Stratify Test A by authority. Report the TWC stratum, the NWS stratum, and the pooled figure separately. No spec change, since §5's construction is indifferent to which authority settles.

**And the pooled figure is not the headline.** The NWS Climatological Report is derived from the same ASOS observations the IEM archive serves. A floor violation in that stratum is close to impossible by construction, so a clean NWS result is reassuring for the wrong reason. Every market from mid-August forward settles on TWC. The TWC stratum is the only one that speaks to the forward regime, and it is the small one.

## Sample ceiling: 68 days, hard

`/markets` returns a rolling window, 2026-06-20 → 2026-08-26. `/events` reaches back to 2021 (14,930 settled event-days) but `/markets?event_ticker=` is empty for anything older, confirmed independently. `KXHIGHNY-26MAY20` returns an empty array. There is no paid tier that fixes this and no archive to fall back on.

Consequences, stated before the numbers arrive:

- Total sample: 21 cities × 68 days ≈ 1,428 city-days. Holdout: 9 cities × 68 ≈ 612.
- TWC stratum: ~13 days × 21 cities ≈ 270 city-days, of which ~117 are holdout.
- **Nominal n overstates power badly.** 21 cities on the same calendar day share a synoptic weather regime and share whatever TWC's methodology does that day. The independent unit is closer to the *date* than to the city-day-bucket-hour triple. §5's rule-of-three bound must therefore be computed on date-clustered units, or it will claim confidence the data does not contain. This supersedes the naive reading of §5's n ≥ 5,000.
- Everything here is summer. Any edge found is a summer edge. Do not scale on it without a winter re-test.

## `expiration_value` gives the exact settled temperature

Confirmed: `KXHIGHNY-26AUG25-T79` carries `expiration_value: 78.00`, `result: yes`, consistent with "less than 79". `KXHIGHNY-26JUL23-T79` carries `79.00`, `result: no`. The field is populated on settled markets across the sample.

§2 argued that recovering the settled *bucket* was sufficient because the bucket is what pays. That argument stands. But the exact value is free, so:

**Decision.** Test A's primary statistic becomes the signed divergence `D = expiration_value − (final observed max from IEM)`, per city-day, reported as a distribution per authority. The dominated-bucket violation count of §5 becomes a derived secondary. Strictly more information, same test, no redesign.

`D > 0` is the safe direction, since settlement reading above observation keeps the floor intact. The eleven-city check already suggests a small positive mean gap (~0.8 °F), consistent with settlement using finer-grained data than hourly METAR. Measure it, do not assume it. And use the same observation basis for `M_H` and for the final max in §6's residual table, so that offset cancels inside the table.

## Deviation approved

Walking `/events` in addition to `/markets`, read-only, no parsed data. It is what made the 68-day ceiling visible. That was the right call. An invisible ceiling is how a sample-size problem becomes a confidence problem three weeks later.

## Split, taken as printed

- **Train (12):** AUS, CHI, DEN, LAX, MIA, TATL, TBOS, TDC, TOKC, TPHX, TSATX, THOU
- **Holdout (9):** NY, PHIL, TDAL, TLV, TMIN, TNOLA, TSAN, TSEA, TSFO

The split lands at 57/43 against §7's 70/30 target. §7 says take the printed assignment, so it is taken. NY landing in holdout is inconvenient, with the most volume and the only station mapping confirmed by hand at Stage 2, and that is not a reason to move it. Moving it would be the tuning trap §8 kills for.

## The sample-size decision tree, committed now

- TWC stratum clean (D ≥ 0 throughout, no dominated-bucket violations) → both authorities track observations, all 612 holdout city-days are usable, Test B proceeds at full sample.
- TWC stratum leaks → NWS-era days are not predictive of the forward regime, only the ~117 TWC holdout city-days count, and that will very likely fall below §8's 30-trade floor → "no conclusion", park C3. Not "lower the threshold until 30 trades appear."

## Open item

One of 21 series did not switch authority. Identify it. Either the listing is stale or it genuinely settles elsewhere, and either way it is a second instance of stale venue documentation worth logging.

## What the checkpoint's corroboration table is not

The station-corroboration table shows 0% observed-above-settled across the twelve train cities. That is not an early Test A result and must not be reported as one. It asks a cruder question, whether the observed max ever exceeds the settled value, on train cities only, for the sole purpose of catching a wrong airport. Test A asks whether a *dominated bucket* ever settles Yes, hour by hour, and is still unrun.

It is also diluted: 82% of those city-days settle on NWS CLI, where agreement with ASOS observations is close to tautological. Whatever signal TWC divergence would produce is averaged into near-invisibility. Reading it as reassurance about the forward regime would be exactly the error §5's stratification exists to prevent.

---

# Correction 1, the 68-day ceiling does not exist

Recorded 2026-08-27, same day, and appended below. The Checkpoint 1 text above stands as written and is wrong on this point.

**What was wrong.** Checkpoint 1 states that market-level history is a hard rolling 68-day window, and this document asserted "there is no paid tier that fixes this and no archive to fall back on." That assertion was made without checking. It is false.

**What is actually true.** Kalshi runs a live tier and a historical tier with a documented cutoff. Verified live, unauthenticated:

- `GET /historical/cutoff` → `{"market_settled_ts":"2026-06-27T00:00:00Z", ...}`. Markets settled before that timestamp are served by `/historical/*`, after it by the live endpoints. `/markets` returning nothing for older events is the tiering working.
- `GET /historical/markets?event_ticker=KXHIGHNY-26MAY20` → returns the ladder, `expiration_value: 92.00`.
- `GET /historical/markets/{ticker}/candlesticks?period_interval=60` → works, with `yes_bid` and `yes_ask` OHLC, same shape as live. Note the path takes no series segment, unlike the live endpoint.
- `GET /historical/markets?event_ticker=KXHIGHNY-25JAN15` → returns markets, from January 2025. Volume is real, at 3,996 contracts on `B35.5` alone.

So the sample is at least 19 months across all four seasons, not 68 summer days.

**Field coverage degrades with age, and the fallback was already designed.** `expiration_value` is populated on Jan 2026 markets (`47.00`) and empty on Jan 2025 markets, where only `result` is present. Test A therefore runs its degree-level statistic `D` wherever `expiration_value` exists and falls back to §2's bucket-recovery method where it does not. §2 argued the bucket is sufficient because the bucket is what pays; that argument now earns its keep.

**Legacy tickers do not resolve.** `HIGHNY-25JAN15` returns empty; `KXHIGHNY-25JAN15` returns markets. Walk the `KX` series only.

## What this changes, and what it pointedly does not

**Changed.** The sample-size decision tree in Checkpoint 1 was built on a false ceiling and is void. Test B is no longer sample-starved, §6's month cells are no longer degenerate, and the summer-only external-validity limit is lifted, so winter is testable now.

**Not changed, and this is the part not to lose in the good news.** The deep archive adds nothing to the TWC-authority stratum, because TWC settlement began around 2026-08-13. That stratum is ~13 days × 21 cities however far back the history goes, and it grows only with the calendar, at roughly 21 city-days per day. Test A's forward-relevant question is exactly as underpowered as it was an hour ago. More history answers seasonality and strategy questions; it does not answer the divergence question, and the two must not be allowed to blur.

*Corrected 2026-09-03. Checkpoint 1's "57/43" is the city ratio, 12 and 9 of 21.
§7 targets a ratio by city-day count, which is also what `stations.py` prints.
By city-day on the live tier that ratio is 816 / 551 = 59.7/40.3
(`data/station_proposal.json`, 4,896 / 3,306 markets at six per ladder), and over
the full 10,677 settled city-days the archive opened up
(`scratch/fetch_hist2.log:75-95`), the realised split is 64.5/35.5. This
correction voids Checkpoint 1's sample-size decision tree and never revisited
that number. §7 still says take the printed assignment, and it is taken.*

## Seasonal stratification

Season joins settlement authority as a stratification dimension in the same run. Do not pool and do not defer. Report winter, spring, summer and autumn separately, holdout discipline applied within each.

Pooling is a regime-mixture problem. The premise of C3, that by late afternoon the day's maximum is substantially determined, is a summer fact. In winter the daily maximum frequently occurs at an odd hour, on a warm front at 2am, and the running-max floor of §5 still holds while the residual distribution of §6 widens and shifts. A pooled figure would average two different games and describe neither. If the edge exists only in summer, that is a finding worth having explicitly.

---

# Correction 2, §6's residual table is fit per-city, on a frozen pre-period

Recorded 2026-08-27, and appended below. The §6 text stands as written and is internally contradictory.

**The conflict.** §6 keys the residual-warming table on `(hour H, calendar month, city)` *and* says it is fit "from training cities only." A holdout city then has no cell and cannot be priced. Both clauses cannot hold at a trade site. I stopped the pipeline, which is the correct behaviour at a once-only run.

**Which clause was wrong.** "Training cities only." It applied holdout hygiene reflexively to a component where it does not belong.

The holdout exists to stop the trading *rule* being tuned to the data that evaluates it. Every free choice in that rule (the 10¢ threshold, the cell keys, the 200-observation floor, the fill assumption, the size cap) is fit on training cities and frozen before the holdout runs. That discipline is untouched.

The residual table is not part of that. It is estimated from IEM weather observations. Seattle's afternoon warming climatology says nothing whatsoever about what Kalshi's quotes did in Seattle. Withholding a city's own climate from its own fair value protects nothing.

**And Option 2 would manufacture a false negative.** Residual warming is a local property. A table pooled across twelve training cities averages marine-layer, desert and continental regimes into a number describing none of them, then applies it to Seattle. The resulting fair values would be systematically wrong at every holdout city, the strategy would show no edge, and the cause would be the estimator. C3 would die for the wrong reason. Under §8 that is not a recoverable error, because the holdout runs once.

**Binding resolution.** The table is keyed `(H, month, city)` and fit from that city's own IEM observations, identically for training and holdout cities.

**With one mandatory addition, which is the real risk here.** Fitting a city on its own full history includes the backtest days themselves, using a day's own outcome to price that day. That is lookahead, and it is a worse error than the one being corrected. So:

> The table is fit on IEM observations strictly before 2025-01-01, frozen once, and applied unchanged to every backtest day in both splits.

A fixed pre-period. It is clean, it is identical across splits, it is constant across the backtest, and it removes an entire class of off-by-one bug at no cost in realism. ASOS history at these stations runs decades, so a `(hour, month, city)` cell holds roughly 900 observations against §6's floor of 200. The floor stays live and does not bind. All twelve months populate, so the seasonal stratification of Correction 1 is supported.

**Unchanged.** Threshold, cell keys, observation floor, fill assumption, size cap, all frozen on training cities before the holdout runs. Changing any of them after seeing the holdout is still the §8 kill.

---

# Correction 3, Checkpoint 1's offset-cancellation reasoning was wrong

Recorded 2026-08-27, at the Test B fit, before the holdout, and appended below. The Checkpoint 1 text stands as written.

**What was wrong.** Checkpoint 1 instructed: use the same observation basis for `M_H` and for the final max in the §6 residual table, "so that offset cancels inside the table." Measured, it does not cancel.

The table's output is compared against buckets defined on the settlement value. So the observation-to-settlement offset, mean +0.8 °F, sd 0.74, re-enters at the bucket-membership step, downstream of the table, where no internal cancellation can reach it. The dispersion does more damage than the location. A +1 °F recentring cuts worst calibration error from 0.397 to 0.209 and does not fix it.

*Corrected 2026-08-28: "mean +0.8 °F, sd 0.74" pairs NWS/summer's mean with the NWS_CLI stratum's sd. The NWS_CLI stratum is mean +0.72, sd 0.74 (`scratch/test_a.log:26`); NWS/summer is +0.80, sd 0.71. Same slip as the one `RESULTS.md` §1 records for its §6; the argument turns on the dispersion, which was quoted correctly. Text above left standing.*

The pipeline reported that shift to size the limitation and correctly did not apply it. Applying it would have been the §8 kill, changing the rule to chase a diagnostic, after the diagnostic had been seen and before the holdout had been run.

**The measured consequence.** §6's fair value is severely overconfident. It says 0.95+ where reality is 0.713, and 0.00-0.05 where reality is 0.097.

## Adverse selection is built into the entry rule, by construction

The §6 rule trades where `|fair − quote| ≥ 10¢`, and I disclosed that it takes the largest edge when several buckets qualify. Both choices select on maximum disagreement with the market. When the model is worse than the market, maximum disagreement is maximum *model error*, so the rule systematically picks the buckets where its own fair value is most wrong.

That is why mid-bucket buys settle at 9.1% while the 0.95+ calibration bin settles at 71.3%. The gap between those two numbers is the selection effect.

**General form, worth carrying to any future test.** A rule that trades on the size of its disagreement with the market is selecting on its own estimation error unless the model is demonstrably the better forecaster. Establish that first, or the entry threshold is an error-maximiser.

## The real finding is the Brier comparison

Over 235,145 bucket-hours:

| Forecaster | Brier |
|---|---|
| §6 model | 0.1739 |
| Kalshi mid-quote | 0.0772 |

The market's quote is more than twice as accurate a forecast, and it wins in every probability bin. No recalibration rescues a strategy that must trade against a forecaster twice as good as its own, because there is no edge to calibrate toward.

*Corrected 2026-09-03: "it wins in every probability bin" was never computed. `check_calibration.py` printed that claim off the aggregate Brier alone and no per-bin comparison existed in the pipeline. On the comparison the committed `figures/calibration.json` supports, absolute calibration error inside each forecaster's own bins, the quote is better calibrated in eleven of twelve bins and the model is closer in the 0.30-0.40 bin. The Brier comparison and the factor of more than two stand. Text above left standing.*

§9's stated prior, "the observation is public and free and this is the obvious thing to do with it", is confirmed. It was written down before the test, and it held.

This measurement is the publishable output of Stage 3, ahead of Test A: a pre-registered, reproducible finding that Kalshi's daily-temperature markets are well calibrated against public observation data, with the counter-hypothesis tested and rejected on its own committed criteria.

**Sibling study.** The same method, applied to Kalshi's NFL and NBA player-prop markets, is at https://github.com/anaborne/kalshi-prop-calibration. There the pre-registered statistic passed and the pass was traced to a measurement artifact in the venue's mid-quote, so the two studies fail in different ways and should be read together.

---

# Correction 4, the 2025-01-01 pre-period does not precede the backtest

Recorded 2026-09-03, after the holdout, and appended below. Correction 2 stands as written and is wrong on the date it chose.

**What was wrong.** Correction 2 set the residual table's pre-period at 2025-01-01 and described it as fixed and constant across the backtest. The date was chosen while Correction 1 had established only that the market archive reached back "at least 19 months", which put its floor near January 2025. The pull reached 2021-08-06 (`scratch/test_a.log:4`), so the fit window and the backtest window overlap by 3.4 years.

**What it costs.** For any backtest day before 2025-01-01, the `(city, month, H)` cell that prices that day contains that day's own `(M_H, final max)` pair. The holdout run covers 1,463 distinct dates and only 602 calendar days lie between 2025-01-01 and 2026-08-25, so at least 861 of those dates, 58.85% of them, fall inside the fit window. The fit run is the same shape at 1,559 trade dates, and so are the 235,145 bucket-hours behind the Brier comparison. Each cell holds about 930 observations, so a day contributes roughly 0.1% of its own price, and the direction flatters the model. It does not overturn a losing verdict. Correction 2 called this class of error worse than the one it was fixing, and it was present anyway.

**Why the check did not catch it.** `verify_preperiod()` asserted that no observation dated on or after the cutoff entered the table. It never asserted that the backtest days postdate the cutoff, which is the other half of the same claim. `test_b.py` describes that check as the reason the cutoff is "asserted in code, not trusted", and it could not see this.

**Binding resolution.** `PREPERIOD_END` is 2021-08-01, at or before the earliest market date in the sample. IEM observations reach back to 1995 at twenty of the twenty-one stations and to 1998-04-28 at Austin (`scratch/fetch_obs_totals.log:2-22`), so the fit window is 23 to 26 years deep and a `(city, month, H)` cell still clears §6's floor of 200. `verify_preperiod()` now asserts that the earliest date in the market universe falls on or after the cutoff and exits if it does not.

**What this does not change.** The published numbers were produced under the 2025-01-01 cutoff and are not re-run here, because the `data/` cache is not committed and the pull is on the order of 10⁴ requests. So for the published sample the lookahead Correction 2 set out to remove is removed only for the post-2025 portion. Threshold, cell keys, observation floor, fill assumption and size cap are untouched.
