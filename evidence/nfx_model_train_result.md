# NFCE-X M1: train-stage result and a bounce diagnostic (27 Oct 2026, 14:50–14:53)

**Protocol:** `nfx_model_protocol.md`, SHA-256 `fc66f7892dcc59ce57ee247e3849205751e7dd2e72f1edbad60fd0e13c955881`. **Code:** `tools/nfx_model.py --stage train`. 4.64 M rows, 140 features, 213 stocks. **Validation (2025) and the final (2026) are NOT run.**

## Walk-forward inside 2022–24 (each test period unseen by its model)
| Test | M1 IC | Trades/day | Gross bp | **Net bp** | 95% CI | p | Ridge B1 net |
|---|---|---|---|---|---|---|---|
| 2023 H1 | 0.058 | 8.8 | +30.7 | **+15.7** | +8.1 … +22.7 | 0.0001 | −5.4 |
| 2023 H2 | 0.054 | 4.7 | +25.7 | **+10.7** | −0.3 … +21.6 | 0.06 | −4.4 |
| 2024 | 0.036 | 2.8 | +18.4 | **+3.4** | −12.5 … +19.5 | 0.16 | −5.1 |

## Diagnostic before using the one-time validation look: the same predictions, entry 15 minutes later
| Test | Gross bp | **Net bp** | 95% CI | p |
|---|---|---|---|---|
| 2023 H1 | +8.5 | **−6.5** | −14.8 … +2.8 | 0.98 |
| 2023 H2 | +3.4 | **−11.6** | −23.0 … −0.3 | 0.92 |
| 2024 | +3.5 | **−11.5** | −33.0 … +7.0 | 0.90 |

## What it means
- **Most of M1's edge sits in the first 15 minutes after the decision bar.** That is the signature of **bid-ask bounce:** the 3-minute closes are last-traded prices, and a bar that closed on the bid tends to "rebound" to the mid. No trade can capture that, because buying means paying the ask.
- The edge also **shrinks fold by fold** (+15.7 → +10.7 → +3.4).
- **Decision: the 2025 validation look is NOT spent on this M1.**

## Next (an amendment registered before any 2025/2026 look)
- **M1-A1:** labels from an executable entry. Enter at the next 3-minute bar's open (or later), not at the decision bar's close.
- Report the delay curve: entry at +3, +6 and +15 minutes.
- Same model and trading rule otherwise.
- If the edge survives a realistic entry on 2022–24, then and only then run 2025 once.
