# Index alignment (H3, H4) and meta-labeling: results (22 Oct 2026, evening)

**Protocols** (each hashed before its run):
- `best_practice_tests_protocol.md`, SHA-256 `016cf9a434e9432c5d1d404e596e18e9a6a4a7678cbe667746e36c7dd8f0f0ae` (16:20);
- `meta_label_protocol.md`, SHA-256 `d733482202f3bcdda9f32f67378a2a5a53070ade3d0e208b18632e01186c30f7` (17:40).

**Trades:** the stock 3m V0 trades on 210 F&O stocks (Upstox 3m, current costs), the same list as H1.
**Code:** `tools/leads_2day.py h3`, `tools/meta_label.py`.
**NIFTY state:** from `hist50/NIFTY_5m.pkl`, as registered.

## H3 / H4: trade only with the index. Train 2022–24: both FAIL (Bonferroni family, p < 0.025 needed)
| Trades | n | Win % | Gross R | **Net R** | Day-block 95% | PF |
|---|---|---|---|---|---|---|
| All (V0) | 16,598 | 51.5 | +0.051 | −0.270 | −0.290..−0.249 | 0.66 |
| Counter-aligned or flat (dropped by H3) | 4,988 | 50.2 | +0.030 | −0.293 | −0.324..−0.262 | 0.61 |
| **H3: aligned with NIFTY** | 11,610 | 52.1 | +0.060 | **−0.260** | −0.286..−0.233 | 0.69 |
| **H4: aligned + before 12:00** | 5,868 | 52.8 | +0.059 | **−0.217** | −0.252..−0.181 | 0.75 |

- **The engine already trades mostly with the index:** 70% of its signals are aligned.
- **Alignment helps a little** before costs (+0.060 vs +0.030R), not after.
- **22 Oct:** the counter-index SELLs were the minority case, not the rule.

## Meta-labeling: a second model chooses which signals to take: FAIL
**Model:** gradient boosting on 8 entry-time features, fitted on 2022–23.

**Threshold chosen on 2024** (mean net R of the trades taken):

| p ≥ | 0.40 | 0.46 | 0.50 | 0.52 | 0.56 | **0.58** | 0.60 |
|---|---|---|---|---|---|---|---|
| Trades | 5,830 | 5,245 | 3,374 | 2,460 | 884 | **550** | 343 |
| Net R | −0.254 | −0.249 | −0.239 | −0.233 | −0.235 | **−0.197** | −0.234 |

**Fixed at 0.58.**

| Period | All trades | Base win % | AUC | Taken | Win % | **Net R** | Day-block 95% | PF |
|---|---|---|---|---|---|---|---|---|
| 2024 (tuning) | 5,966 | 51.6 | 0.518 | 550 | 54.7 | −0.197 | −0.311..−0.095 | 0.88 |
| **2025 (validation, one look)** | 6,912 | 50.4 | **0.511** | 751 | 51.3 | **−0.327** | −0.424..−0.229 | 0.59 |

- **AUC 0.51–0.52:** the model can barely tell winners from losers, as the 1.09 M-sample direction study found.
- **The trades it picked in 2025 lost more** than average.
- **Next step:** none. Under the protocol, 2026 is not run.

## What tonight's four tests say together
| Test | Idea | Result |
|---|---|---|
| Cap (2022–24) | Fewer same-direction pile-ups | FAIL (17% milder worst day) |
| H1 | Morning only | FAIL (−0.224R) |
| H2 | Scanner SELL only | FAIL (−0.065R) |
| H3 / H4 | With the index / + morning | FAIL (−0.260 / −0.217R) |
| Meta-labeling | A model picks the trades | FAIL (2025 −0.327R, AUC 0.511) |

**The common cause:**
- **Edge vs costs:** the stock 3m signals have a gross edge of about +0.05R per trade, and costs take about 0.3R (their stops are about 0.3–0.4% from the entry).
- **No filter closes that gap:** not time, direction or model confidence. Filters can only choose among trades that each lose after costs.
- **What could change it:** a different entry/stop design with much wider stops relative to costs, or much cheaper execution. Both are new, registered studies, not tweaks.
- **The WIDE account** (2× stops) starts measuring the first of these live tomorrow.
