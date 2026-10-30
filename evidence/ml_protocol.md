# Machine-learning study: protocol (20 Oct 2026, ~01:20 IST, before any model was trained)

**Question:** using lakhs of 5-minute bars, how well can we forecast (a) the **direction** and (b) the **size** of the next move on NIFTY and BANKNIFTY? And is any of it worth trading after today's costs?

## Data
- Upstox 5m, 3 Jan 2022 – 31 Jul 2026, regular session only, special sessions dropped.
- NIFTY, BANKNIFTY and India VIX, plus the Nifty 50 stocks that Upstox lists (for breadth features and as extra training rows).

## Decision points (samples)
- Every 15 minutes, from the bar closing at 09:45 to the bar closing at 14:15, on every session.
- **Index samples (the instruments traded):** NIFTY and BANKNIFTY.
- **Stock samples:** the same times on each stock. They add training rows for the pooled direction model and test generality.

## Targets (all measured strictly after the decision bar's close)
- **D60:** the sign of the return over the next 60 minutes (12 bars).
- **R60:** the log of the next-60-minute range, (max high − min low) / price.
- **TB:** "target before stop": whether price touches +1.0 × ATR before −1.0 × ATR (ATR14 of 5m bars), within 60 minutes or by 15:20. Computed for the long side; the short side is symmetric.

## Features (causal: only data up to the decision bar's close)
| Group | Features |
|---|---|
| Returns | 1, 3, 6, 12 and 24 bars; since the open; the overnight gap; the first-30-minute return (Gao et al.) |
| Position and level | distance to session VWAP (volume proxy for indices); range so far / daily ATR14 (previous days); daily ATR14 / price |
| Volatility | realised volatility of the last 12 bars; realised volatility of the previous session |
| Calendar | time of day; day of week; historical expiry-day flag |
| VIX | India VIX level; change over 5 bars; change since the open |
| Breadth | share of Nifty 50 stocks up since the open; share up over the last 12 bars; index return minus the average stock return |
| Stock rows only | relative volume |

## Models (chosen on VALIDATION from this list only)
- **Direction:** logistic regression (standardised; C ∈ {0.1, 1.0}) and histogram gradient boosting (max_depth ∈ {3, 6}, 300 trees, lr 0.05).
- **Range:** HAR-style linear regression (recent realised volatility, previous-day realised volatility, daily ATR, time-of-day mean) and histogram gradient boosting. Quantile gradient boosting gives the 10% and 90% bounds.

## Splits
| Split | Period | Use |
|---|---|---|
| TRAIN | 2022–2024 | Fit models |
| VALIDATION | 2025 | Choose the model and the confidence threshold |
| FINAL TEST | Jan–Jul 2026 | Run **once**, with the validated choice |

## Metrics and pass criteria (FINAL TEST, indices)
**Direction model:**
1. AUC ≥ 0.53 **and** better log loss than the base rate.
2. A trading rule: trade the next 60 minutes in the predicted direction when the probability exceeds the validation-chosen threshold, at **current** costs (dated schedule on 18 Oct 2026, 2 orders, 4 ticks friction).
3. The rule passes only with net R > 0, a day-block 95% lower bound > 0, and ≥ 40 trades.

**Range model:**
1. R² ≥ 0.30 on the log range.
2. Coverage of the 10–90% interval between 75% and 85%.

**TB model:**
- reported for calibration: hit rate by predicted-probability decile.
- If it is well calibrated, it is useful for setting targets.

**Outcome rule:** a model that fails is reported as failed and is not built into the system. A model that passes becomes a registered live paper experiment before any reliance on it.
