# Stage 3 results, C3 weather settlement convergence

Companion to `PREREGISTRATION.md`. That document is the binding spec and is
append-only; this one records what the pipeline measured.

**Verdict: C3 dies at Stage 3.** Test A's floor test passed in the
forward-relevant stratum and leaked in the historical one. Test B's holdout was
run once, as pre-registered, and lost money in every season and every trade
shape by a margin no confidence interval comes close to spanning. §8's kill
criteria are met several times over.

Sections 1-3 were written before the holdout fired; sections 6-8 after.

Everything below cost $0 and used unauthenticated public endpoints.

---

## 1. What was pulled

| | |
|---|---|
| Universe | 21 daily city max-temperature series, all `CLIxxx`-corroborated (Checkpoint 1) |
| Settled markets | 60,906 across two tiers, 8,202 live and 52,704 historical |
| Settled city-days | 10,677 over 1,843 distinct dates, 2021-08-06 → 2026-08-25 |
| Seasons | summer 3,328 · spring 3,262 · winter 2,338 · autumn 1,749 |
| Candlesticks | 60,906 / 60,906, hourly, two-sided `yes_bid`/`yes_ask` OHLC. The committed `scratch/fetch_candles.log` ends at 60,753 cached with 153 rate-limited (HTTP 429) markets pending, and the retry pass that completed the cache was not captured, so the final count rests on `fetch_candles.py --status` at the time and on the commit message of the commit that completed the candlestick cache |
| Observations | 6,821,602 hourly ASOS rows (6,780,268 usable), 21 stations, 1995 → 2026 |

*Corrected 2026-08-27, second entry. §6 gave the observation-to-settlement
offset as "mean +0.8°F with sd 0.74". The pair matches no single stratum. sd
0.74 is NWS_CLI's, whose mean is +0.72; the one stratum with mean +0.80 is
NWS/summer, whose sd is 0.71. Both are printed to two decimals in §2's own table
two sections earlier. The argument is unaffected, since it turns on the
dispersion, which was quoted correctly. A document that corrects a round-up in
its own favour does not get to leave one that merely sounded tidier.*

*Corrected 2026-08-27: the observation row count read "6.9M" here, rounded up
from 6,821,602. The exact counts are `scratch/fetch_obs.log`, summed over the
1995-2026 pass. A repo that argues for running the cheap check at the moment of
writing does not get to round in its own favour.*

*Corrected 2026-09-03, candlestick row. That row rests the final 60,906 / 60,906
count on `fetch_candles.py --status` at the time and on the commit message of the
commit that completed the cache. Neither is in this repository. `git rev-list
--count HEAD` returns 1: the repository was republished as a single commit,
`4ee3b84`, on 2026-08-29, the commit named there no longer exists in its history,
and the `--status` output was never committed. So the final count has no
committed source. What is checkable is `scratch/fetch_candles.log`, which ends at
60,753 cached with 153 markets errored on HTTP 429. `README.md` carries the
single-commit disclaimer for the pre-registration timestamps only.*

**Two tiers.** An earlier pass of mine reported a hard 68-day
market history and asserted no archive existed. That was wrong and the assertion
was made without checking. Kalshi tiers settled markets at
`/historical/cutoff` (`market_settled_ts` 2026-06-27); `/markets` returning
nothing for older events is the tiering working. Correction 1 records this.

**Tier stamps order the attempt, they do not decide it.** 84 markets settled
2026-06-20, a week *before* the cutoff, are returned by the live listing but
404 on the live candlestick path and resolve on the historical one. Both paths
are tried. Trusting the stamp absolutely would have dropped those markets
silently, and a 404 here is indistinguishable from a market that never traded.

**Settlement authority is not constant.** Three eras, all verified from
`rules_primary`:

| Authority | city-days | span |
|---|---|---|
| UNSPECIFIED, rules name no source at all | 455 | 2021-08-06 → 2022-04-26 |
| NWS Climatological / Daily Climate Report | 9,975 | 2022-03-04 → 2026-08-13 |
| The Weather Company | 247 | 2026-08-14 → 2026-08-25 |

The NWS stratum pools three wordings of one product (`Climatological Report`,
`Daily Climate Report`, `NWS's Daily Climate Report`). The UNSPECIFIED stratum is
kept separate. Assuming an unstated source matches a stated one is the error §1
made.

---

## 2. Test A, the safety test

Run on all 21 cities. Stratified by settlement authority (Checkpoint 1) and by
season (Correction 1). Rounding variants disagree, so §5's pessimistic rule binds
and the unrounded variant is the result.

### Primary statistic, D = settled value − final observed max

| Stratum | city-days | dates | mean | sd | min | p01 | p50 | p95 | max | D<0 |
|---|---|---|---|---|---|---|---|---|---|---|
| TWC | 247 | 12 | +0.86 | 0.67 | 0.0 | 0.0 | 1.0 | 2.0 | 3.0 | 0 |
| NWS_CLI | 9,971 | 1,623 | +0.72 | 0.74 | −13.0 | 0.0 | 1.0 | 2.0 | 13.0 | 90 |
| NWS winter | 2,159 | 360 | +0.58 | 0.78 | −8.0 | −0.2 | 0.4 | 2.0 | 13.0 | 25 |
| NWS spring | 3,201 | 457 | +0.74 | 0.78 | −13.0 | −1.0 | 1.0 | 2.0 | 5.0 | 43 |
| NWS summer | 3,043 | 442 | +0.80 | 0.71 | −4.0 | 0.0 | 1.0 | 2.0 | 4.0 | 16 |
| NWS autumn | 1,568 | 364 | +0.70 | 0.66 | −1.0 | 0.0 | 1.0 | 2.0 | 3.0 | 6 |
| UNSPECIFIED | 455 | 262 | +0.54 | 0.84 | −8.0 | −0.6 | 0.0 | 2.0 | 4.0 | 11 |

### Secondary, §5's dominated-bucket violations

**§5's measure is violations over (city-day, bucket, H) triples.** Stated
explicitly because a D<0 city-day rate is a different statistic on a denominator
~28× smaller and must never be compared to the 0.5% line.

| Stratum | numerator | denominator | rate | 95% CI (date-clustered) | city-days |
|---|---|---|---|---|---|
| TWC | 0 violating triples | 5,169 dominated-bucket-hours | 0.0000% | n/a | 0 |
| NWS_CLI | 511 | 274,552 | 0.1861% | [0.1306%, 0.2481%] | 39 |
| NWS winter | 116 | 72,576 | 0.1598% | [0.0643%, 0.2789%] | 10 |
| NWS spring | 318 | 80,919 | 0.3930% | [0.2384%, 0.5548%] | 23 |
| NWS summer | 52 | 72,008 | 0.0722% | [0.0162%, 0.1497%] | 4 |
| NWS autumn | 25 | 49,049 | 0.0510% | [0.0000%, 0.1378%] | 2 |
| UNSPECIFIED | 0 | 0 | n/a | n/a | 0 |

UNSPECIFIED's zero denominator is structural. All 709 of those 2021-2022 markets
are single `"N° or higher"` thresholds with no upper bound, so no bucket there is
ever dominatable. They are single-threshold contracts.

511 violating triples are 39 distinct city-days on 39 distinct dates, so one
bad day recurs at every afternoon hour. The triple count is §5's literal
measure; city-days and dates are what correspond to independent events.

### §5's pre-committed verdict

- **TWC, clean band.** 0 violations over 5,169 dominated-bucket-hours, clearing
  §5's n ≥ 5,000. Test B proceeds.
- **NWS_CLI, leaks band.** 0.1861%, above 0 and below 0.5%.
- Spring's CI upper bound reaches 0.5548%, past the 0.5% kill line. The point
  estimate says proceed; the interval does not exclude "C3 dies."

### Violation margin, and why zero is not the headline

Further degrees of negative D required to flip a dominated bucket. 0 = already a
violation.

| Stratum | eligible | unreachable | median | ≤1°F | ≤2°F | ≥3°F |
|---|---|---|---|---|---|---|
| TWC | 217 | 30 | 2 | 14.3% | 52.1% | 47.9% |
| NWS_CLI | 8,406 | 1,565 | 2 | 19.5% | 64.3% | 35.7% |

Over half of eligible city-days sit within 2°F of a flip, in both strata. A clean
record built on 2°F of headroom is fragile, and in the NWS stratum that
fragility already cashed out. "Unreachable" city-days, where the settled value
sat in the ladder's open-ended lower tail so no downward divergence could flip
anything, are excluded.

---

## 3. Three findings recorded before `--fit`

### 3.1 A max-over-cells statistic is uninformative below ~11¢

While checking whether deepening the observation archive introduced bias, the
first instrument used was "worst fair-value difference across months, traded
hours and bucket offsets." It maxes over ~1,260 cell comparisons and is an
extreme-value statistic dominated by sampling noise.

Its noise floor was measured directly, from two residual tables built from the
same era by random day split, where bias is impossible by construction:

| stn | noise floor | 1995 vs 2010 table | 2005 vs 2010 table |
|---|---|---|---|
| NYC | 11.04¢ | 7.47¢ | 2.89¢ |
| MDW | 11.97¢ | 7.85¢ | 2.53¢ |
| LAX | 10.65¢ | 8.17¢ | 2.85¢ |
| SAN | 11.54¢ | 7.85¢ | 3.33¢ |
| PHL | 11.12¢ | 4.95¢ | 4.03¢ |

Every difference between candidate archive depths sits below the pure-noise
floor. An earlier pass cited NYC's 7.47¢ as material against the 10¢ entry
threshold; it is not distinguishable from noise, and that citation was wrong.

**This is a general property of the instrument.** Any figure of
this shape (a maximum of per-cell fair-value differences) must not be cited as
evidence anywhere in this project below roughly 11¢, by anyone, in any later
section. Where systematic effects matter, use a signed mean, where noise cancels
across cells and bias survives.

*Corrected 2026-09-03. The floor in that table is measured on the wrong sample
shape and is several times too wide. The null splits the modern era (2010-2024,
about 5,479 days) into two disjoint halves of about 2,739 days each. The
comparison it judges is a table on 1995-2024, about 10,958 days, against a table
on 2010-2024, a superset against a subset of itself. The two share every day the
smaller one has. The sampling standard deviation of a per-cell difference scales
as sqrt(1/n1 + 1/n2) for two disjoint halves and as sqrt((nA−nB)/nA² +
(nA−nB)²/(nA²nB)) for a nested pair, which puts the printed floor about 2.8×
too wide for the "1995 vs 2010" column and about 4.0× too wide for the "2005 vs
2010" column. Rescaled, the floors against the 1995 column are NYC 3.90¢, MDW
4.23¢, LAX 3.76¢, SAN 4.08¢, PHL 3.93¢, and all five observed differences sit
above their floor. Against the 2005 column the rescaled floors run 2.7¢ to 3.0¢
and four of the five observed differences sit above them. The sentence above
retracting the earlier 7.47¢ NYC citation therefore does not stand: 7.47¢ is
about 1.9× its correctly scaled floor. The "uninformative below roughly 11¢" rule stated
here, carried forward at §8's first caveat and in `README.md`, is calibrated to
a sample shape this project never used. `check_depth_bias.py` now builds the
null at the sizes and the nesting of the comparison it benchmarks. The table
above is not re-run here, because the `data/` observation cache is not
committed.*

### 3.2 TWC is in the clean band, and the power limit travels with it

Test B proceeds because TWC's stratum is clean by §5's pre-committed table. That
permission carries a limit that does not expire when a PnL number arrives:

- **12 dates.** The rule-of-three bound on date-clustered units is 25% per
  date. Checkpoint 1 supersedes §5's naive n ≥ 5,000 reading precisely because
  21 cities on one calendar day are not 21 independent observations.
- Correction 1 is explicit that the deep archive does not enlarge this
  stratum. TWC settlement began ~2026-08-13; it grows only with the calendar,
  at ~21 city-days per day.
- The near-tautological source diverged. NWS derives from the same ASOS
  observations IEM serves and still produced 89 D<0 city-days out of the 9,510
  with an exact settled value (0.936%; `scratch/test_a.log:271`, and §2's table
  shows 90 because it also counts one city-day whose negative sign was
  recovered from the settled bucket without an exact value). Applying that
  rate to TWC's 247 city-days predicts 2.31 negative days; zero were observed,
  P(zero | NWS rate) = 0.098 (`scratch/test_a.log:274-276`). That is weak evidence TWC diverges *less*
  than NWS. It is not evidence it behaves the same, and not close to any
  conventional threshold.

**Read TWC as clean-but-underpowered.** "No evidence of a leak", never "the
floor holds." No Test B result retires this limit. A profitable backtest on a
strategy whose safety rests on 12 dates is a profitable backtest on 12 dates.

### 3.3 The forward regime is unmeasured in the season where the historical regime leaks hardest

TWC's 12 dates are all in August. All 247 TWC city-days are summer.

The NWS stratum leaks worst in spring, at 0.3930% with a CI to 0.5548%, against
a 0.5% kill line, 5× the summer rate and 8× autumn. Summer is the *mildest*
season in the only stratum with enough dates to measure seasonality at all.

So the forward-relevant authority has been observed only in the season where its
predecessor leaked least, and is entirely unobserved in the season where its
predecessor leaked hardest, the season whose confidence interval touches the
kill line.

**This is the standing caveat on every Test B result.** Any edge Test B reports
is a summer edge measured under a settlement authority observed for 12 summer
days. It carries no evidence about spring, which is both the untested season and
the one the historical record flags as most dangerous. Correction 1 already
forbids pooling seasons. Here that separation carries the verdict, beyond the
shape of the tables.

*Corrected 2026-08-28: this section quoted spring as "0.3802%, CI to 0.5490%"
and "17× autumn", the figures from the run before the 2,950 strike-less
markets were counted (§5). §2's table was updated to the re-run when the fix
landed; this paragraph was not. The operative figures are 0.3930%, CI to
0.5548%, and 0.3930/0.0510 ≈ 8× autumn (`scratch/test_a.log:96,98`).*

---

## 4. Method notes worth keeping

**Integer settlement.** Every populated `expiration_value` in the sample is a
whole degree, so a "less than 101" market's yes-set has supremum 100, not 101.
Domination is evaluated against the attainable set, which declares domination
slightly more often than a continuous reading and makes the test stricter.

**Observation archive starts 1995, the ASOS deployment boundary.** The
Automated Surface Observing System was commissioned across the US network
through the mid-1990s. Data from 1995 forward comes from the same automated
measurement process, cadence and siting regime as the feed the strategy trades
against; earlier data is a different process reporting the same units. The
boundary is chosen for measurement-process continuity. No sample-size target and
no per-cell count entered the choice.

A 2005 start was considered and rejected. It would have halved NYC's
reporting-density step change (24 → ~30 obs/day at 2005, worth +0.122°F of mean
residual at H=13, t = +4.5, and −0.013¢ of signed fair value). Choosing a cutoff
because it improves a diagnostic is selecting a nuisance parameter on that
diagnostic, which is the tuning pattern §6 exists to prevent.

*Corrected 2026-09-03. "24 → ~30 obs/day at 2005" has no committed source.
`check_depth_bias.py` fixes its eras at 1995-2009 and 2010-2024, so nothing in
this repository measures a density break at 2005, for NYC or anywhere else. The
committed pair is 26.1 → 30.7 obs/day across the 1995-2009 / 2010-2024 boundary
(`scratch/check_depth_bias.log:41`). The +0.122°F of mean residual at H=13, with
t = +4.5 and −0.013¢ of signed fair value, checks out as printed
(`scratch/check_depth_bias.log:96`), and the reason for rejecting a 2005 start is
unaffected.*

**Station mapping caught a real error.** `KXHIGHTHOU` is Houston Hobby
(`CLIHOU`), not Bush Intercontinental. IAH runs +0.38°F *above* settlement across
68 train city-days where every correctly-mapped city runs below it. An IAH
mapping would have manufactured floor violations out of nothing but a wrong
airport. `KXHIGHCHI` is Midway (`CLIMDW`), not O'Hare.

---

## 5. Two silent bugs found late, and what they cost

Both excluded data without raising anything. Recording them because that
failure mode, a quietly smaller sample, is the one this pipeline exists to
catch, and it caught them late.

**Candle schema differs by tier.** Live candles carry `volume_fp` and suffix
price keys `_dollars`; historical candles carry bare `volume` and bare keys.
Reading only the live spelling returned `None` for every historical quote, and
the size cap turned that into a skipped market, silently excluding all 52,704
historical markets and collapsing the first Test B fit onto the live tier's 68
summer days. What gave it away was the date count in the output.

2,950 markets (4.8%) carry no strike fields at all, only `yes_sub_title`
prose. Code reading strike fields alone returns "no upper bound", and a bucket
with no upper bound is never dominated, so those markets contributed to neither
the numerator nor the denominator of §5's rate. This hit Test A as well as Test
B. `buckets.py` adds a subtitle parser validated against the 57,956 markets
carrying both representations: 57,956 agree, 0 disagree, 2,949 recovered, 1
genuinely unbounded. Test A's leak rate rose from 0.1657% to 0.1861% once those
markets were counted. `python buckets.py` reprints that validation from cache
and reconciles it against the pull, at `scratch/buckets_validation.log`.

---

## 6. Test B fit, and why the rule was already dead before the holdout

Rule frozen on the 12 training cities. Every free choice is a pre-registered
constant, so nothing was fitted. The training run is a check.

| Shape | trades | mean/trade | 95% CI | ¢/contract | settle accuracy |
|---|---|---|---|---|---|
| dominated-bucket sell | 117 | −$1.3102 | [−2.4879, −0.1718] | −7.13¢ | 87.2% |
| mid-bucket buy | 13,129 | −$1.8632 | [−1.9673, −1.7627] | −10.04¢ | 9.1% |
| other | 19,484 | −$1.4637 | [−1.5567, −1.3697] | −9.45¢ | 66.2% |

A 9.1% settle rate on buckets the model priced as cheap is not a market
efficiency result. A losing backtest is either an efficient market or a broken
estimator, and only a calibration curve separates them.

### The §6 fair value is severely overconfident

Training cities, 235,145 evaluated bucket-hours:

| §6 predicts | n | actually settles | error |
|---|---|---|---|
| 0.00-0.05 | 112,141 | 0.097 | +0.072 |
| 0.10-0.20 | 27,291 | 0.257 | +0.107 |
| 0.30-0.40 | 11,758 | 0.373 | +0.023 |
| 0.60-0.70 | 2,865 | 0.301 | −0.349 |
| 0.70-0.80 | 2,996 | 0.353 | −0.397 |
| 0.90-0.95 | 3,115 | 0.571 | −0.354 |
| 0.95-1.01 | 25,828 | 0.713 | −0.267 |

**Checkpoint 1's reasoning on one point does not survive measurement.** It
required the same observation basis on both sides of the residual table so that
the observation-to-settlement offset would "cancel inside the table." It does
not cancel. The table's output is compared against buckets defined on the
*settlement* value, so the offset, and more damagingly its dispersion, mean
+0.72°F with sd 0.74 on the NWS stratum (`scratch/test_a.log:26`; TWC runs
+0.86 with sd 0.67 at `:24`), re-enters at the bucket-membership step. A +1°F
recentring cuts worst error from 0.397 to 0.209 without fixing it, because the
problem is dispersion as much as location.

That recentring was measured and not applied. Changing the rule to chase a
diagnostic is precisely §8's kill.

### Recalibration would not have rescued it

Brier score on the same 235,145 bucket-hours, lower is better:

| forecaster | Brier |
|---|---|
| §6 fair value | 0.1739 |
| market mid-quote | 0.0772 |

The market quote is the better forecast at every probability bin, by a
factor of more than two. §9's honest prior, *"the likeliest outcome is that
late-afternoon quotes already track observed readings, because the observation
is public and free and this is the obvious thing to do with it"*, is confirmed.
A strategy that must trade against a forecast twice as accurate as
its own does not have a calibration problem to fix; it has no edge to calibrate
toward.

*Corrected 2026-09-03. "The market quote is the better forecast at every
probability bin" was never computed. `check_calibration.py` printed that sentence
whenever the aggregate Brier favoured the market, and no per-bin comparison
existed anywhere in the pipeline. On the per-bin comparison the committed
`figures/calibration.json` supports, absolute calibration error inside each
forecaster's own bins, the quote is closer in eleven of the twelve bins and the
model is closer in the 0.30-0.40 bin, where the model is off by 0.026 and the
quote by 0.048. The Brier figures and the factor of more than two are unaffected.
`check_calibration.py` now computes the per-bin comparison and prints the count
it finds, and the figure title was corrected in place.*

**How the market's forecast is constructed, and why it does not decide this.**
The quote scored above is `(yes_ask.high + yes_bid.low) / 2`, the midpoint of
the *widest* spread observed in the hour. That pair is not chosen here. It is
§6's fill assumption, pre-registered as deliberately punitive because only
hourly OHLC is available and a buyer should be assumed to pay the worst ask in
the hour. Reusing it to score the market as a forecaster is a different purpose,
and it is not self-evidently neutral, so it is measured.

Rescoring on the hour's closing mid, `(yes_ask.close + yes_bid.close) / 2`, over
the same 235,145 bucket-hours, every one of which carries both closes, so the
event set is identical and the model is rescored on it unchanged:

| forecaster | Brier |
|---|---|
| §6 fair value | 0.1739 |
| market, widest-spread mid, the headline | 0.0772 |
| market, closing mid | 0.0683 |

The construction moves the market's Brier by 0.0089, against a
model-versus-market gap of 0.0967. It moves it in the direction that
*understates* the market. The punitive fill pair makes the market look worse
than a closing mid does, so the headline is the conservative version of the
comparison and the true gap is wider. Printed at `scratch/check_calibration.log:60-63`.

---

## 7. Test B holdout, run once

9 holdout cities, 19,348 trades over 1,463 dates, 308,873 contracts.

| Shape | trades | dates | mean/trade | 95% CI | ¢/contract | settle accuracy |
|---|---|---|---|---|---|---|
| dominated-bucket sell | 78 | 18 | −$4.1176 | [−5.7160, −2.6552] | −23.46¢ | 94.9% |
| mid-bucket buy | 7,819 | 938 | −$1.5971 | [−1.7350, −1.4573] | −9.06¢ | 11.1% |
| other | 11,451 | 1,350 | −$1.2427 | [−1.3690, −1.1177] | −8.38¢ | 62.8% |

| Season | trades | mean/trade | 95% CI | date-clustered CI | ¢/contract |
|---|---|---|---|---|---|
| winter | 3,683 | −$1.7475 | [−1.9547, −1.5382] | [−2.1345, −1.3297] | −10.69¢ |
| spring | 7,102 | −$1.3493 | [−1.4965, −1.2062] | [−1.6018, −1.0894] | −8.51¢ |
| summer | 6,729 | −$1.2891 | [−1.4472, −1.1309] | [−1.5684, −1.0068] | −8.12¢ |
| autumn | 1,834 | −$1.2790 | [−1.5960, −0.9630] | [−1.8085, −0.7333] | −8.03¢ |

Pooled, and not the headline: −8.75¢/contract, win rate 19.8%, total −$27,039.

**Sensitivity, reported not corrected.** Removing the intra-hour lookahead
(pairing `M_{H-1}` with hour H's quotes) makes it *worse*, at −10.98¢/contract over
21,985 trades. The frozen rule's small lookahead was flattering it.

Dominated-bucket sells realised 94.9% settle accuracy against the 98.1% they
need to break even. The shape §6 singled out fails on its own arithmetic, and
Test A's measured leak is why. At −23.46¢/contract it is the worst shape in the
book, which is the outcome §6 predicted when it said this shape's entire EV
lives in the tail-error rate.

*Corrected 2026-09-03. 94.9% is the rate at which those buckets settled Yes,
which for a sell is the rate at which the trade lost. `test_b.py` scored
`in_bucket(settled, bounds)` for every shape, so the sell row printed the
complement of the statistic that has to clear the breakeven bar. Those 78 sells
settled No on 5.1% of trades: the bucket the model called impossible is the one
that settled, on 74 of 78. The 98.1% breakeven is §6's figure for a 2¢ bucket
and does not describe this book. The entry rule forces a mean sell price of at
least 10¢, and −23.46¢/contract against a 94.9% Yes rate puts the mean fill near
73¢, where breakeven is about 29% settle-No. The shortfall is about 24 points of
settle-No. The paragraph above reads it as 3.2 points. The attribution to
Test A's measured leak does not survive either: that leak is 0.186% and the
in-book Yes rate on these trades is 94.9%, a factor of 500 that the paragraph
never reconciles. The −23.46¢/contract and the confidence interval are
unaffected. §6's training-shape table above carries the same inversion: its
87.2% is the Yes rate on 117 sells, which settled No on 12.8% of trades, and its
"other" row pools both sides so 66.2% is not one statistic. `test_b.py` now
scores the statistic side-aware and computes the breakeven from the prices
actually filled; the committed logs predate that fix and print the uncorrected
pair.*

---

## 8. Verdict

**C3 dies at Stage 3.** §8's criteria, applied per shape and per season as
Correction 1 requires:

| Unit | verdict |
|---|---|
| mid-bucket buy | DIES, 95% CI upper bound −$1.4573, entirely below zero |
| dominated-bucket sell | DIES, 95% CI upper bound −$2.6552, entirely below zero |
| winter | DIES, CI [−1.9547, −1.5382] |
| spring | DIES, CI [−1.4965, −1.2062] |
| summer | DIES, CI [−1.4472, −1.1309] |
| autumn | DIES, CI [−1.5960, −0.9630] |

Not a near miss in any stratum. Every confidence interval lies wholly below
zero, on both the i.i.d. and the date-clustered bootstrap.

*Corrected 2026-09-03. That holds as printed for the four seasons and is not
checkable for the two shapes. `test_b.py` computed the clustered intervals for
every shape and `by_shape()` printed only the i.i.d. one, so
`scratch/test_b_holdout.log:13-15` carries no clustered interval and
`data/test_b_results.json` is not committed. The seasons' clustered intervals are
at `:23-30` and all lie below zero. The clustered interval matters most for the
dominated-bucket sell, at 78 trades over 18 dates, where clustering could widen
it materially. `by_shape()` now prints it, and the committed log predates that.*

No threshold was lowered, no cell key changed, no fill assumption relaxed, and
the holdout was run once. §8's final criterion, that any such change after
seeing the holdout kills C3, did not need to bind, because nothing was changed.

### What survives as a result

Test A stands on its own merits, as §5 anticipated. It is a measured public
statement about whether a market settling ~$100k/day per city settles where free
public data says it should:

- Over 274,552 dominated-bucket-hours on the NWS regime, the floor leaks at
  0.186%, worst in spring at 0.393% with a date-clustered CI reaching 0.555%,
  past §5's own kill line.
- Over 5,169 dominated-bucket-hours on the TWC regime, zero violations, but on
  12 dates, all summer, with a 25%-per-date bound.
- The signed divergence `D` has a left tail reaching −13°F.

### The caveats that outlive the verdict

1. **The ~11¢ noise floor.** Any "worst fair-value difference across cells"
   figure is uninformative below roughly 11¢ (§3.1). This is a property of the
   instrument and applies to anything downstream.
2. **TWC's clean record is 12 dates.** P(zero violations | the NWS divergence
   rate) = 0.098. Weak evidence TWC diverges less; not evidence the floor holds.
3. TWC is unmeasured in spring, the season where the historical regime leaks
   hardest and where its CI touches the kill line. Nothing here tests that.

None of these were needed to reach the verdict. They would have been needed had
the verdict gone the other way, so they are not quietly dropped now that it did
not.

---

## 9. Open

- One series never switched authority, `KXHIGHTSAN`, TWC-only across all 42 of
  its settled markets. Not a stale-documentation case, because it launched
  2026-08-19, after the switch, so it has no NWS era to switch from. Its
  `rules_primary` reads: *"If the
  maximum temperature recorded at San Diego (CLISAN) for Aug 25, 2026, is greater
  than 89° fahrenheit according to The Weather Company, then the market resolves
  to Yes."*
- The stale Kalshi help-centre documentation noted in §1 remains live.
