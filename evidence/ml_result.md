# Machine-learning study: result (20 Oct 2026)

**Protocol:** `ml_protocol.md` (SHA-256 `402dc99319…`), frozen before training.
**Data:** 1,093,115 decision points, 52 symbols (NIFTY, BANKNIFTY and the Nifty 50 stocks), every 15 minutes, 3 Jan 2022 – 31 Jul 2026.
**Tools:** `nfce_engine/tools/ml_study.py`. Causality is guaranteed by `tests/test_ml_study.py`: rewriting the entire future changes no feature.
**Training:** all models were trained on 2022–2024 only.

## Direction of the next 60 minutes: FAIL (at validation)
| Model | 2025 AUC (all / index) | 2025 accuracy, index | Best trading rule, 2025, current costs | 2026 AUC, index (information only) |
|---|---|---|---|---|
| Logistic C=0.1 | 0.501 / 0.507 | 50.3% | −0.25R (1,062 trades) | 0.522 |
| Logistic C=1.0 | 0.501 / 0.507 | 50.3% | −0.25R | 0.522 |
| Gradient boosting, depth 3 | 0.504 / 0.492 | 49.4% | −0.20R | 0.536 |
| Gradient boosting, depth 6 | 0.504 / 0.493 | 49.2% | −0.26R | 0.522 |

- Log loss is no better than the base rate.
- The most confident 10% of index predictions were right 48–51% of the time in 2025.
- **With a million examples and the literature's features, next-hour direction is a coin flip.** Every trading rule loses after costs, in 2025 and in 2026.

## Target (+1 ATR) before stop (−1 ATR): no useful skill
- AUC 0.505 (2025) and 0.518 (2026).
- Predicted probabilities spanned 0.39–0.54, but the actual hit rates stayed at 0.43–0.49.
- Base rate: 46% of +1 ATR targets are reached before an equal stop.

## Size of the next 60-minute move: PASS (validation and final)
| | 2025 (validation) | Jan–Jul 2026 (final, one shot) | Pass bar |
|---|---|---|---|
| R² of log range, gradient boosting, all symbols | 0.405 | 0.328 | ≥ 0.30 |
| R² of log range, gradient boosting, indices | 0.333 | **0.372** | ≥ 0.30 |
| 10–90% interval coverage, all symbols | 80.3% | 80.1% | 75–85% |
| 10–90% interval coverage, indices | 77.0% | **78.3%** | 75–85% |

The simple HAR-style linear model is weaker, especially on the indices (R² −0.41 / −0.02), so the time-of-day, VIX and breadth features matter.

## What this means
1. **No model here can tell where the market will head in the next hour** better than a coin flip by a margin that pays for trading. This agrees with the large US studies.
2. **How far the market will move can be forecast reliably.** The forecast explains about a third of the variation, and it gives an 80% band that really contains about 80% of outcomes. That is the honest basis for **setting targets and stops**: size them to the forecast range, not to fixed multiples.
3. **Proposed registered experiment R4:** range-calibrated targets. T1 at the forecast median move and the stop beyond the forecast 10% bound, tested live on paper against the current fixed 1R/2R/3R targets. Integrating it needs a live 5-minute bar feed for the features (the Upstox intraday candle endpoint).
