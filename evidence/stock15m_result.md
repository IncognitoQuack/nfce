# 15-minute NFCE on F&O stocks: result (21 Oct 2026, evening)

**Protocol:** `stock15m_protocol.md`, SHA-256 `eacb254ee6d20d3d3fab5dad8200eafe460a7629a1277f0b9addb15df50936f5`, hashed at 17:54 IST, before the run.
**Code:** `nfce_engine/tools/stock15m_research.py`. **Data:** the 3m study's candles, resampled to 15m.

## Train stage, 2022–2024 (current costs, one lot, all out at T1)
| Variant | Trades | Win % | Gross R | **Net R** | Day-block 95% | PF | Paper ₹ |
|---|---|---|---|---|---|---|---|
| F0, every 15m signal | 4,056 | 44.5 | +0.001 | **−0.176** | −0.207..−0.146 | 0.69 | −27.5 L |
| F1, cost share ≤ 20% | 2,800 | 45.6 | +0.008 | **−0.132** | −0.169..−0.095 | 0.74 | −18.1 L |

- **Cost share of risk:** median 17% (10th percentile 10%, 90th 27%), half the 3m figure, as expected.
- **But the edge before costs disappears:** +0.001R (3m: +0.041R). Wider stops fixed the cost problem and lost the edge.
- **Both variants fail training,** so validation and the final stage are not run.

## Applied
Nothing changes in the live system: the stock signals stay as information, and the ₹5 L account takes their option legs at ¼ risk only. This result supports the account's new cost gate (skip a trade whose round trip is more than 25% of its risk): on stocks, costs decide the outcome.
