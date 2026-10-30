# Range model vs the option market's implied move: forward measurement, no trades (registered 26 Oct 2026, 11:40 IST, before the first scored session)

**Why:**
- The next-hour range model is the one tool in the project with measured skill (R² ≈ 0.31–0.37 out of sample, `SCOPE.md`).
- Options price the same quantity.
- If the model's forecast is informative about **realized vs implied**, that comparison is a tradable signal: sell defined-risk premium when the model expects much less movement than the options price, buy a straddle when it expects more.
- This protocol only **measures**. It places no trades, not even on paper.

**Code:** `nfce_engine/tools/range_vs_implied.py`; tests `nfce_engine/tests/test_range_vs_implied.py`.

## Data (all recorded live, read-only)
- **Forecasts:** `nfce_bridge/data/nfce.db`, table `range_forecasts`. Each row is NIFTY or BANKNIFTY, at bar closes every 15 minutes, with model M1 (primary), HAR and ENS. `q10/q50/q90` are quantiles of log(next-hour high − low over price), and `realized` is the outcome.
- **Option chains:** `nfce_bridge/data/study_chain_YYYYMMDD.db` (once a minute).

## The implied move (fixed here)
- **Snapshot:** the first snapshot at or within 3 minutes after the bar close. **Expiry:** the nearest one that does not expire that day. **ATM strike:** the strike nearest the spot. **Straddle** = the mid of the CE plus the mid of the PE.
- **Conversion:**
  - total move: σ_total = straddle / (S·√(2/π));
  - per-hour σ = σ_total / √(trading hours left to the expiry's 15:30), weekdays, 6.25 hours a day;
  - expected range E[range₁ₕ] = √(8/π)·σ_hour.
- **Cross-check:** the same from the chain's IV, in calendar time.
- **Known limitation:**
  - spreading variance evenly ignores the U-shaped day and expiry-day effects, which the model does know;
  - so a constant bias is expected, and the claims below are built to survive it.

## Sample
- **From 27 Oct 2026.** 26 Oct is the pilot: used to build the method, and excluded from every claim.
- **Judged once**, at the first close where there are **≥ 20 sessions and ≥ 250 M1 forecasts per index** with a realized value.

## Claims (family of 3, Bonferroni, so each needs p < 0.0167; day-clustered: one value per session)
| Claim | Statistic | Supports |
|---|---|---|
| **C1, intraday variance premium** | mean of (log implied − realized) > 0, t-test on the session means | options over-price the next hour |
| **C2, the model is the better forecaster** | mean of (\|implied − realized\| − \|q50 − realized\|) > 0, on the session means | the model forecasts realized range better than the options |
| **C3, tradable disagreement** | slope > 0 in the regression of (realized − log implied) on (q50 − log implied), pooled, with standard errors clustered by session | when the model says "less than priced", realized really is lower relative to the price |

**Also reported:**
- C1–C3 per index, per model (HAR, ENS), and with each 15-minute time slot demeaned (C3);
- realized/implied by quintile of model/implied;
- 80% band coverage;
- the straddle vs IV cross-check.

## What follows
- **If C3 passes:** a separate, registered **forward paper** options test (defined-risk sells when model/implied is in its lowest quintile; long straddles when it is in the highest), with its own costs from the recorded bid/ask. **Never straight to money.**
- **If C3 fails:** the model's skill is already in the option price. Close this lead.
- **Nothing here changes any live rule.**
