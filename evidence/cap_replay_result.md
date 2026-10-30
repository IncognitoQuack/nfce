# Same-direction cap: historical replay result (22 Oct 2026, evening)

**Protocol:** `cap_replay_protocol.md`, SHA-256 `feb8d1b9856c05bde77e7dfa4c531bff6de61e787b107e8348fc24ec9020b320`, registered at 13:40 before the run.
**Code:** `nfce_engine/tools/cap_replay.py`. It runs on the trades of `tools/stock3m_research.py`, whose only change is the entry time added to each row.
**Data:** 50 NIFTY-50 stocks, Upstox 3m, 2022–24, current costs.
**Reproduction check:** V0 gives the same 4,460 trades at −0.338R as `stock3m_result.md`.

## Train, 2022–24
| | Trades | Skipped | Win % | Net R / trade (day-block 95%) | Mean day | Worst day | 5th-pct day | Max drawdown | Total | ₹ (1 lot) |
|---|---|---|---|---|---|---|---|---|---|---|
| V0, every signal | 4,460 | 0% | 50.7 | −0.338 (−0.369..−0.306) | −2.08R | −12.15R | −6.61R | 1,507R | −1,507R | −27.3 L |
| CAP, ≤ 2 same-direction per 30 min | 3,947 | 12% | 51.2 | −0.331 (−0.362..−0.300) | −1.81R | −10.13R | −5.90R | 1,305R | −1,305R | −23.2 L |

## Verdict: FAIL
- **What the rule required:** the worst day and the maximum drawdown each better by at least 25%, a better 5th-percentile day, and net R per trade no more than 0.02R worse.
- **What happened:**
  - the worst day improved by 17%;
  - the drawdown improved by 13%;
  - the 5th-percentile day and the per-trade result improved slightly.
- **Next step:** under the protocol, the 2025 validation is not run.

**What it means:**
1. The cap does what it is meant to: fewer pile-ups on one move, so the worst days are milder.
2. It cannot fix the strategy. Each trade still loses about a third of its risk after costs, so the drawdown is simply the steady loss (maximum drawdown = total loss: the curve only goes down).
3. Skipping 12% of a losing strategy's trades loses 12% less money. That is not an edge.
4. The cap stays in the forward test as V3 (`live_variants_protocol.md`). Nothing changes live; the owner asked for the replay only.
