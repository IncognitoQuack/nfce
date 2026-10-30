# 15-minute NFCE on F&O stocks: do wider stops beat the costs? Protocol (21 Oct 2026, evening, before any result)

## Why
The 3-minute stock study (`stock3m_result.md`) failed because costs took a median 35% of each trade's risk: the 3m stops (about 0.3% of price) are too tight, against an edge before costs of about +0.04R. On 15-minute bars the same engine's stops are several times wider, so the same costs are a much smaller share of the risk. If the stock signals are ever to carry real size in the ₹5 L account, this is the cheapest honest test: same data, same engine, same execution rules, one change (the timeframe).

## Data
- The same Upstox 3m candles as `stock3m_protocol.md` (2022-01 to 2026-10-19, the 50 NIFTY-50 stocks and India VIX), resampled to 15m bars anchored at 09:15. Only complete bars (five 3m bars) are kept.
- **Limitation:** spot prices stand in for the stock futures; survivorship bias (today's NIFTY-50 list).

## Signals
- The NFCE engine, `Params(instr="STOCK")`, tf = 15, with the same heavyweights (HDFCBANK, ICICIBANK, RELIANCE, INFY, BHARTIARTL) and India VIX, resampled the same way.

## Execution (identical to the 3m study)
- **Entry:** at the engine's entry (the close of the signal bar). **Exit:** stop at the engine's SL; target T1 = entry ± 1R, all out; otherwise the close of the 15:00 bar (15:15).
- **Fill rules:** `research2._walk` (stop first, gap fills at the open, entry-bar checks).
- **Costs (current):** `futures_cost_points`, units = round(700,000 ÷ entry), 2 orders, friction 0.02% of price per side.

## Variants (2)
| Name | Rule |
|---|---|
| **F0** | every 15m signal |
| **F1** | only signals with cost share ≤ 20% |

## Stages (unchanged discipline)
| Stage | Window | Survives iff |
|---|---|---|
| Train | 2022–2024 | mean net R > 0 and one-sided p < 0.05 on day means |
| Validation | 2025 | mean net R > 0 and p < 0.05 / k (k = train survivors) |
| Final (one shot) | 2026-01-01 to 2026-10-19 | mean net R > 0, day-block 95% lower bound > 0, PF ≥ 1.10, ≥ 100 trades |

## Use
- **If a variant passes all three stages:** the bridge computes 15m stock signals as well, and the ₹5 L account trades their option legs at normal (1×) risk with that cost gate. The 3m stock signals stay at ¼ risk.
- **Otherwise:** nothing changes in the live system; the result is reported in full.
