# Range-forecast benchmark: result (20 Oct 2026)

**Protocol:** `range_benchmark_protocol.md`, SHA-256 `a9f0afa0a3b12a09f17b859cbb4b89d8f44e2314025748bebdd11efcb5722c4a`, hashed at 12:14 IST before the run.
**Code:** `nfce_engine/tools/range_benchmark.py`. **Raw output:** `range_benchmark_result.json`. **Run:** once.

## Data check
- **Overlap (24–31 Jul 2026):** Upstox and Yahoo 5m closes are identical for NIFTY and BANKNIFTY (median difference 0.000%), and VIX differs by 0.02%. Set B is usable.
- **Set B:** 2,052 index decision rows over 54 sessions, 1 Aug – 19 Oct 2026. No model had seen this data.

## Fresh set B (Aug–Oct 2026): the main result
| Model | Pinball (pooled) | NIFTY | BANKNIFTY | 10–90% band held (NIFTY / BANKNIFTY) | R² of q50 | Band width (log) |
|---|---|---|---|---|---|---|
| M0 shipped R4 model | 0.0981 | 0.1016 | 0.0947 | 76.0% (72.3% / 79.7%) | 0.317 | 0.964 |
| **M1 refit + conformal** | **0.0978** | 0.1010 | 0.0945 | 77.2% (74.7% / 79.7%) | 0.310 | 0.975 |
| B1 seasonal (previous 20 sessions) | 0.1118 | 0.1152 | 0.1083 | 71.6% | 0.083 | 0.947 |
| B2 VIX-only quantile regression | 0.1063 | 0.1119 | 0.1007 | 82.1% | 0.200 | 1.160 |
| B3 HAR+VIX linear quantile regression | 0.0981 | **0.1005** | 0.0958 | **79.6% (76.7% / 82.5%)** | 0.303 | 0.999 |

**By time of day (pinball / band held):**

| Model | before 11:15 | 11:15–12:59 | 13:00 onwards |
|---|---|---|---|
| M0 | 0.0890 / 81% | 0.1003 / 77% | 0.1079 / **68%** |
| M1 | 0.0893 / 82% | 0.0994 / 78% | 0.1073 / 69% |
| B3 | 0.0907 / 84% | 0.1012 / 79% | **0.1043 / 75%** |

**M0 − best baseline (B3):** +0.000004 pinball, 95% day-block interval −0.0021 to +0.0022, i.e. no difference.

## Secondary set A (Jan–Jul 2026, already used by R4; all models fitted on 2022–2025)
| Model | Pinball | 10–90% band held | R² q50 |
|---|---|---|---|
| R4 architecture (gradient boosting) | **0.0976** | 78.8% | **0.379** |
| B1 seasonal | 0.1263 | 68.5% | 0.044 |
| B2 VIX-only | 0.1073 | 85.3% | 0.256 |
| B3 HAR+VIX | 0.1002 | 81.2% | 0.345 |

## Pre-declared claims, as decided by the rules
| Claim | Result |
|---|---|
| "Best on this benchmark" (M0 beats every baseline on fresh data, interval below 0) | **NO.** M0 beats the seasonal and VIX-only baselines clearly, but it **ties** the linear HAR+VIX model. |
| "Reliable bands" (75–85% on both indices, M0 or M1) | **NO.** NIFTY 72.3% (M0) and 74.7% (M1), just under 75%. The bands are too narrow after 13:00 (68–69%). |
| Adopt M1 for R4 | **YES.** M1's pinball is ≤ M0's (0.0978 vs 0.0981) and its coverage is closer to 80% (77.2% vs 76.0%). It is installed as `models/range_r4.pkl` (SHA-256 `b321c77a…`), and R4 is re-registered before any live data. |

## What this means, plainly
1. **The forecast has real, repeatable skill.**
   - It explains about 31% of the variation in the next hour's range on unseen data (R² 0.31), against 8% for a seasonal rule.
   - That skill held from 2025 (validation) through Jan–Jul 2026 (one-shot) to Aug–Oct 2026 (fresh).
2. **It is not "best in class".**
   - A linear model on four volatility inputs (recent and previous-day realised volatility, daily ATR and VIX) does as well.
   - Most of the skill is volatility clustering plus VIX, which is well known.
   - The gradient-boosted model adds nothing measurable over it on fresh data. The earlier R² of 0.37 (Jan–Jul 2026) fell to 0.31.
3. **The bands run a little narrow, especially in the afternoon.**
   - Alerts after 13:00 should treat the 80% band as roughly a 70% band.
   - R6 measures this live and will report it.
4. **The M1 adoption is within fitting noise.**
   - Refitting the same model with a different row order changes the pinball by about 0.0004, more than M1's 0.0003 advantage.
   - M1 was adopted because the rule said so, not because it is clearly better.
5. **What comes next:** R6 compares M1, the linear model and their average live, on data no one has seen, with a pre-declared judgement after 40 sessions.
