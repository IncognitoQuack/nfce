# R6: live forward benchmark of the next-hour range forecasts (registered 20 Oct 2026, before any live data)

## Why
The range forecast is the one model that has held up out of sample. On fresh Aug–Oct 2026 data (`range_benchmark_result.md`), the calibrated ML model M1 was level with a simple linear HAR+VIX quantile model, and neither model's 80% band was quite reliable on NIFTY. R6 settles the comparison on data that no one has seen yet: the live market from 21 Oct 2026.

## What the bridge records (`nfce_bridge/bridge/service.py: record_range_forecasts`, table `range_forecasts`)
- **When:** at every decision bar close (09:45, 10:00, …, 14:15 IST), for NIFTY and for BANKNIFTY.
- **Forecasts:** three of them, each as log quantiles q10 / q50 / q90 of log(range of the next 12 five-minute bars ÷ the decision close):
  - `M1`: the shipped model (`models/range_r4.pkl`, conformalised);
  - `HAR`: the linear HAR+VIX quantile model (`models/range_har.json`);
  - `ENS`: the average of the M1 and HAR log quantiles.
- **Scoring:** each forecast is scored once its 12 bars are complete, using Upstox 5m candles.
- **Refusals:** a forecast the guards refuse (stale or incomplete data, missing VIX, history lag) is not recorded. Refusals are not imputed.

## Seasonal baseline (computed by the scorer from the same live data)
`SEAS`: for each index and decision time, the 10/50/90% quantiles of the previous 20 sessions' realised values. It exists only from the 21st session onwards, and every comparison with SEAS uses only those rows.

## Judgement: one look only
- **When it is judged:** the first time each index has ≥ 600 scored forecasts per model over ≥ 40 sessions. If that hasn't happened by **31 Mar 2027**, the verdict is INCONCLUSIVE.
- **Scorer:** `nfce_engine/tools/registry_eval_r6.py --db nfce_bridge/data/nfce.db`.
- **Statistics:** pinball loss is the mean over q ∈ {0.1, 0.5, 0.9}. Intervals come from a day-block bootstrap (2,000 resamples) of the pooled difference.

| Claim | Holds iff |
|---|---|
| **C1 calibrated** | M1's 10–90% coverage is within 75–85% for NIFTY and for BANKNIFTY |
| **C2 skill** | M1's pinball is below SEAS's (pooled, SEAS-eligible rows), with the 95% interval of (M1 − SEAS) entirely below 0 |
| **C3 ML vs linear** | M1's pinball is below HAR's, with the 95% interval of (M1 − HAR) entirely below 0. If the interval covers 0: "no difference shown" |
| **C4 ensemble** | ENS's pinball is below both M1's and HAR's, with the 95% interval of (ENS − the better of the two) entirely below 0 |

## Use of the result
- **If C4 holds:** ENS would replace M1 for R4 targets, only in a newly registered experiment (never mid-run).
- **If C1 fails:** the bands are reported as "too narrow" (or "too wide") on every alert.
- **Not a trading test:** R6 says nothing about profit; R4 tests whether range targets help trading.
