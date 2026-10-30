# Multi-year research: result (20 Oct 2026)

**Protocol:** `research_protocol.md` (SHA-256 `93174267e80ab693…`), frozen before any result.
**Data:** Upstox 5m, 3 Jan 2022 – 31 Jul 2026, 1,135 sessions, regular session only. Dropped: 09:10 pre-open bars, 15:30+ bars and 3 Muhurat sessions.
**Tools:** `nfce_engine/nfce/research.py` (8 unit tests) and `nfce_engine/tools/research_run.py`.
**Clarification made before results:** momentum has no stop, so its R = 0.25 × daily ATR14 of previous days.

## Stage 1 — TRAIN (2022–2024): 84 configurations
| Family | Configs | Positive after costs | Best net R | Median net R |
|---|---|---|---|---|
| N: NFCE engine | 24 | 6 | +0.163 (n=45, below the 100-trade minimum) | −0.061 |
| O: opening-range breakout | 48 | 23 | +0.084 | −0.003 |
| V: VWAP trend | 4 | 1 | +0.004 | −0.016 |
| M: first-hour momentum | 8 | **0** | −0.104 | −0.123 |

**21 survivors** met all three conditions: ≥ 100 trades, net > 0, and positive in ≥ 2 of 3 years. 19 of them are opening-range breakouts, plus NFCE N0/N4 on NIFTY 15m and VWAP trend on NIFTY.

## Stage 2 — VALIDATION (2025)
The pass rule: net > 0 **and** one-sided p < 0.05 (day-clustered), on ≥ 40 trades.

| Best survivors in 2025 | n | Net R | p | PF |
|---|---|---|---|---|
| ORB NIFTY, 30-min range, opposite stop, EOD exit, volatility gate | 183 | +0.067 | 0.17 | 1.19 |
| ORB NIFTY, 60-min range, mid stop, EOD exit, volatility gate | 137 | +0.043 | 0.35 | 1.08 |
| VWAP trend NIFTY, 3×ATR stop | 171 | +0.022 | 0.40 | 1.05 |
| The other 18, including every Bank Nifty ORB and both NFCE variants | | **negative** | | |

**No candidate passes. Per the protocol, the process stops; the Jan–Jul 2026 final-test data is left untouched** for a future registered experiment.

## Stage 2b — the same three at CURRENT costs (STT 0.05% on futures since 1 Apr 2026)
| Candidate | Train net R (dated → current) | 2025 net R (dated → current) |
|---|---|---|
| ORB NIFTY 30 opp eod volgate | +0.022 → **−0.069** | +0.067 → **−0.008** |
| ORB NIFTY 60 mid eod volgate | +0.021 → **−0.130** | +0.043 → **−0.089** |
| VWAP NIFTY 3.0 | +0.004 → **−0.111** | +0.022 → **−0.078** |

## Conclusions
1. **Opening-range breakouts on NIFTY had a small, real-looking edge before costs.** It was roughly +0.08 to +0.19R per trade, positive across 2022–2025. That was enough at the lower STT of 2022–2025, though never statistically convincing.
2. **The April 2026 STT increase removes that edge for index futures.** At today's costs, every candidate is negative.
3. **NFCE's 9-factor score is not among the best designs on 4.5 years of data.** Simpler opening-range rules did better.
4. **Bank Nifty ORB failed validation in every variant.** First-hour momentum failed in training.
5. **The software is unchanged by this research**, because nothing validated. The finding to act on is about execution cost. A trade whose edge is around +0.1–0.2R before costs needs execution costing well under 0.1R: liquid ITM options with tight spreads (experiment R1), or no trading.
