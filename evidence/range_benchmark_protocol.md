# Range-forecast benchmark: protocol (written 20 Oct 2026, before any result of this benchmark was computed)

## Question
Is the shipped R4 range model (`nfce_bridge/bridge/models/range_r4.pkl`, trained 2022-01 to 2026-07-31) better than simple, well-known ways of forecasting the next hour's range? Does a calibrated version do better still? The answers are decided by the rules below, fixed before the data is looked at.

## Target and decisions
- **Target:** log((max high − min low) over the next 12 five-minute bars ÷ close). This is `R60` in `tools/ml_study.py`, NIFTY and BANKNIFTY only.
- **Decision bars:** bars starting 09:40, 09:55, …, 14:10, every 15 minutes, the same as in training. A row counts only if all 12 future bars are in the same session.

## Data
- **History:** Upstox 5m index bars and India VIX, 2022-01-03 to 2026-07-31 (the R4 training data).
- **FRESH test set B: 2026-08-01 to 2026-10-19.** These are Yahoo Finance 5m bars for `^NSEI`, `^NSEBANK` and `^INDIAVIX`, downloaded on 19 Oct 2026 for the hold-out study; the range model has never been evaluated on them. Index features need about a year of history (daily ATR), so the Yahoo bars are appended to the Upstox history.
- **Overlap check, before use:** the two sources overlap on 24–31 Jul 2026. If NIFTY or BANKNIFTY 5m closes differ by more than 0.05% (median absolute) on that overlap, set B is reported as unreliable.
- **Secondary set A: 2026-01-01 to 2026-07-31.** This window was already used by the R4 one-shot test, so it is not fresh and is reported as secondary only. On set A, every model is fitted on 2022–2025.

## Competitors (all use only information available at the decision bar)
| Name | Description | Fitted on |
|---|---|---|
| **M0** | the shipped R4 model (gradient-boosted quantile regression, 19 features) | 2022-01 to 2026-07 (as shipped) |
| **M1** | the same model refitted on 2022–2025, then conformalised: additive log-space shifts to q10 and q90 chosen so that exactly 10% / 90% of 2026-01..07 index rows fall below them (q50 shifted to its median residual) | 2022–2025, calibrated on 2026-01..07 |
| **B1 seasonal** | for each index and decision time, the empirical 10/50/90% quantiles of the target over the previous 20 sessions | rolling, past data only |
| **B2 VIX** | linear quantile regression of the target on log(VIX) and decision-time dummies | same span as M0 |
| **B3 HAR+VIX** | linear quantile regression on log rv12, log rv_prev, log atr_px, log VIX, rng_atr, expiry flag and decision-time dummies | same span as M0 |

On set A, M0 is replaced by the same architecture fitted on 2022–2025, and M1 is not evaluated (its calibration window is set A).

## Metrics (log space, index rows, per index and pooled)
1. Mean pinball loss over q ∈ {0.1, 0.5, 0.9} (primary).
2. Coverage of the 10–90% band (target 80%).
3. R² of q50 as a point forecast.
4. Mean band width.
5. The same split by time of day: decisions before 11:15, 11:15–12:59, 13:00 or later.

Uncertainty comes from a day-block bootstrap (2,000 resamples) of the pooled pinball difference between the best ML model and the best baseline.

## Pre-declared claims
- **"Best on this benchmark":** the shipped model M0 may be called best only if, on fresh set B, its pooled mean pinball loss is lower than every baseline's, it is lower for each index separately, and the 95% interval of (M0 − best baseline) is entirely below 0.
- **Calibrated: "reliable bands"** only if M0's or M1's 10–90% coverage on set B lies within 75–85% for both indices.
- **Adopting M1 for R4** (it would replace the shipped model and R4 would be re-registered before any live data): only if, on set B, M1's pooled pinball loss is ≤ M0's **and** M1's pooled coverage is closer to 80% than M0's. Otherwise M0 stays.
- Whatever the result, the forecast is a **range** forecast. It does not predict direction and is not a trading edge; R4 tests whether it helps trading.

## One shot
Set B is evaluated once, with `tools/range_benchmark.py`, and all numbers are reported, good or bad.
