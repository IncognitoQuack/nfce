# F&O stock scanner rules: result (20 Oct 2026)

**Protocol:** `scanner_protocol.md`, SHA-256 `5d1cd15139be2e828a11e8fa469aa7ab1ee663e8e9acbbff455c28c7e71d9795`, hashed at 16:15 IST before the run.
**Code:** `nfce_engine/tools/scanner_research.py`.
**Data:** 50 NIFTY-50 stocks, Upstox 5m, at current (2026) costs. All 9 configurations were run.

## Train (2022–2024): net R per trade after current costs
| Rule | 10:15 | 11:15 | 13:15 |
|---|---|---|---|
| **G1 gainer continuation** (buy the top-5 gainers, sell the top-5 losers) | −0.069 (7,135 trades; gross +0.018) | −0.070 (gross +0.016) | −0.072 (gross +0.014) |
| **G2 volume surge** (top-5 relative volume ≥ 1.5×, trade the day's direction) | −0.087 (3,270; gross +0.006) | −0.069 (gross +0.024) | −0.052 (gross +0.041) |
| **G3 reversal** (sell the gainers, buy the losers) | −0.089 (gross −0.003) | −0.089 | −0.095 |

- **Every interval is below zero.** All nine day-block 95% intervals are entirely below 0; the best upper bound is −0.028R (G2 13:15).
- **Profit factors:** 0.68–0.85.
- **Win rates:** 42–47%.

## Verdict
- **No rule survives the training stage.** By the protocol, validation (2025) and the one-shot 2026 test are not run.
- **The edge before costs is essentially zero (+0.01 to +0.04R).**
- **Knowing that a stock is a top gainer, or trading heavy volume, by mid-morning does not predict the rest of its day** well enough to pay for futures costs: STT 0.05% plus friction, about 0.07–0.09R at these stop distances.
- **Caveat:** this universe is the 50 NIFTY stocks, a subset of the 246 F&O stocks. Thinner F&O stocks usually have wider spreads, so costs there would be higher, not lower.

## How the bridge uses this
The owner asked for these lists, so the scanner still sends them, labelled 🔴 NO EDGE with the numbers above. Its levels follow the tested rule exactly (stop 0.5 × daily ATR; T1/T2/T3 = 1R/2R/3R; exit by 15:15). Every pick is paper-traded live in book `scanner`, so live results can be checked against this test.
