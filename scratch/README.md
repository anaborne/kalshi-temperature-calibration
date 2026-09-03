# Run logs

stdout from the actual run that produced [`../RESULTS.md`](../RESULTS.md), kept
so every headline number can be traced to the run that produced it.

| log | produces |
|---|---|
| `fetch_hist.log`, `fetch_hist2.log` | the settled-market universe, both API tiers |
| `fetch_obs.log` | the ASOS observation pull, per station, with usable-row counts |
| `fetch_obs_totals.log` | `fetch_obs.py --summary`, the same table re-read from cache, with the row totals `RESULTS.md` quotes |
| `fetch_candles.log` | the hourly candlestick pull, ending at 60,753/60,906 cached with 153 markets rate-limited (429). The retry that completed the cache was not logged |
| `test_a.log` | Test A, with violation counts, rates, CIs, and every violation printed |
| `test_b_fit.log` | Test B, the fit on training cities, ending in the frozen rule |
| `test_b_holdout.log` | Test B, the single holdout run |
| `check_calibration.log` | the reliability curves and the model-vs-market Brier |
| `check_depth_bias.log` | whether the 1995 archive depth trades variance for bias |
| `buckets_validation.log` | `python buckets.py`, the strike-ladder parser checked against `yes_sub_title`, and the 2,950 strike-less markets reconciled |

`fetch_hist.log` and `fetch_hist2.log` are two passes of the same pull. The
second is the one that stands, after the tier-schema bug in §5 of `RESULTS.md`
was fixed. `fetch_obs.log` likewise contains two pulls, the 2010-2026 pass and
the 1995-2026 pass that superseded it. The later block is the operative one in
both files.

`fetch_obs_totals.log` and `buckets_validation.log` are the two logs here not
produced by the original run. Both re-read the existing cache and pull nothing,
so they report exactly what the original run wrote. They exist because two
figures `RESULTS.md` quotes had no machine-produced source. The observation
total could only be had by summing 21 lines by hand, and the parser-validation
counts behind the 2,950 strike-less markets lived in prose alone, which is
load-bearing prose, since those markets moved Test A's leak rate from 0.1657% to
0.1861%.

**These logs predate the code corrections dated 2026-09-03.** They are the
stdout of the run that produced `RESULTS.md`, and they are not re-run, because
the `data/` cache is not committed and the pull is on the order of 10⁴ requests.
Four of them print something the code no longer prints. `test_b_fit.log` and
`test_b_holdout.log` report the bucket's Yes rate under the heading "accuracy",
which for the sell shape is the rate at which the trade lost, and a 98.1%
breakeven §6 derives for a 2¢ bucket; they also record the 2025-01-01 pre-period
that Correction 4 moves to 2021-08-01. `check_calibration.log` prints "better
forecast at every probability bin" off the aggregate Brier, with no per-bin
comparison behind it. `check_depth_bias.log` prints a noise floor built from a
disjoint half-split of the modern era. Each of those is a dated correction in
`RESULTS.md` or `PREREGISTRATION.md`.

**One redaction.** These logs originally printed absolute paths, which published
the operator's home directory. The prefix was removed on 2026-08-27 and the
scripts changed to log repo-relative paths (`common.short`), so `wrote
/Users/…/trading-venture/data/universe.json` now reads `wrote
data/universe.json`. Nothing else in any log has been altered, no number, no
ordering, no line.
