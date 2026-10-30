# NFCE-X phase 2, model M1: can ~140 factors combined predict the next hour well enough to beat costs? Protocol

**Registered** 27 Oct 2026, ~14:50 IST, before any model is trained or any label is looked at.
**Owner's request:** factor in "all patterns, indicators, momentum, news …" so that the system, not a human, weighs them.

## Data
- **The feature store:** `~/Downloads/nfce_data/nfx_features/` (`tools/nfx_build.py`). 213 F&O stocks, decision bars every 15 minutes, 3-minute history from 2022-01 to 2026-10-21.
- **Features:** every column not starting with `y_` (about 140: momentum, volatility, trend, oscillators, volume, session, 23 candle patterns, structure, daily, cross-sectional ranks, breadth, VIX, results calendar). All are point-in-time; `tests/test_nfx_features.py` proves it.
- **Target:** `y_20`, the log return over the next 20 bars (1 hour), same day only, minus that timestamp's cross-sectional mean (market-neutral), clipped at ±5%.

## Model (ONE configuration, fixed now; no tuning on validation or final data)
- **M1:** `sklearn.ensemble.HistGradientBoostingRegressor(max_iter=300, learning_rate=0.05, max_leaf_nodes=31, min_samples_leaf=500, l2_regularization=1.0, random_state=20261027)`. Missing values handled natively.
- **Baseline B1:** `Ridge(alpha=10)` on the same features, after median imputation and standardization (fitted on train only).
- **Training rows:** decision bars from 09:45 to 14:15 inclusive, so the 1-hour label never crosses 15:15. One day of embargo at each split boundary.

## Trading rule evaluated (fixed now)
- **Decision times:** non-overlapping, at the bars closing 10:15, 11:15, 12:15, 13:15 and 14:15.
- **Positions:** long the 5 highest predictions and short the 5 lowest. Each is held for 20 bars as **stock futures**.
- **Cost:** 15 bp per round trip per position. Measured: STT 5 bp + half-spread 4.6 bp × 2 + fees about 0.8 bp.
- **Trade only** when that position's prediction minus the cross-sectional median is at least 7.5 bp in its direction, so each leg must forecast at least its half of the cost.
- **Variant V-cash (reported, not a separate test):** the long side only, in cash intraday at 12 bp.

## Stages and verdict
1. **Train** 2022-01-01..2024-12-31.
   - Diagnostics: 3 expanding walk-forward folds (train to 2022-12 → test 2023-H1; to 2023-06 → 2023-H2; to 2023-12 → 2024). Report the per-timestamp Spearman IC and net bp.
   - Then fit on all of 2022–24.
2. **Validation 2025, one look.**
   - **PASS requires all of:** M1 net bp per trade > 0; the 95% day-block bootstrap lower bound > 0; one-sided day-block p < 0.025 (Bonferroni over M1 and B1); mean IC > 0 with day-block t > 2.
3. **Final 2026-01-01..2026-10-21, one shot,** only for a model that passed validation, refitted on 2022–25. The same criteria.

## Reported in any case
- IC, the hit rate of the predicted direction, gross and net bp per trade, trades per day, day-block CI and p, worst day, by year;
- the top 20 feature importances (permutation importance on validation);
- B1 alongside M1.

## Prediction written down before running
- Most likely, M1 shows a small positive IC (0.01–0.03): some real short-term information, mostly from volatility, volume and reversal features.
- The net result per trade is most likely still negative after 15 bp, as the earlier ML direction study (AUC 0.51) found on fewer features.
- A PASS would be the first price-based edge found.
- Either way, the importance table tells us which families carry information, which feeds phase 3.
