# 3-minute NFCE on F&O stocks: does a cost gate rescue it? Protocol (21 Oct 2026, ~15:40 IST, before any result)

## Why
On 21 Oct, live paper, the stock 3m engine won 22 of 37 trades but lost ₹13,884 as futures: costs (₹17,156) were 5.2× the gross (₹3,272), because its stops are about 0.3% of price. The obvious fix is to take a futures trade only when costs are a small share of its risk. Before changing the live system, this is tested on four and a half years of 3m data, with the same staged discipline as every other study here.

## Data
- Upstox 3m candles, 2022-01 to 2026-10-20, for the 50 NIFTY-50 stocks plus India VIX (pulled 21 Oct evening). Spot prices stand in for the stock futures.
- **Limitation:** survivorship bias (today's NIFTY-50 list), so results may be optimistic.

## Signals
- The NFCE engine, `Params(instr="STOCK")`, tf = 3: exactly the live stock engine.
- Heavyweights: HDFCBANK, ICICIBANK, RELIANCE, INFY, BHARTIARTL (3m); India VIX 3m.

## Execution (what the live account would do with one lot)
- **Entry:** at the engine's entry (the close of the signal bar).
- **Exit:** stop at the engine's SL; target T1 = entry ± 1R, all out (one lot cannot be split); otherwise at the close of the 15:12 bar (15:15).
- **Fill rules:** stop first in a bar, gap fills at the open, entry-bar checks (`research2._walk`).
- **Costs (current, 2026):** `futures_cost_points`, about ₹7 lakh notional (units = round(700,000 ÷ entry)), 2 orders, friction 0.02% of price per side.
- **Cost share:** round-trip cost in points ÷ R.

## Variants (3)
| Name | Rule |
|---|---|
| **V0** | every signal (as live on 21 Oct) |
| **V1** | only signals with cost share ≤ 20% |
| **V2** | only signals with cost share ≤ 10% |

## Stages
| Stage | Window | Survives iff |
|---|---|---|
| Train | 2022–2024 | mean net R > 0 and one-sided p < 0.05 on day means |
| Validation | 2025 | mean net R > 0 and p < 0.05 / k (k = train survivors) |
| Final (one shot) | 2026-01-01 to 2026-10-20 | mean net R > 0, day-block 95% lower bound > 0, PF ≥ 1.10, ≥ 100 trades |

## Use
- **If a variant passes all stages:** the live stock engine uses that cost gate for futures, and the ₹2 L account may trade it.
- **Otherwise:** stock 3m signals are not traded as futures in the account. They stay as information and as option legs, which have lower costs but cannot be backtested (no option history). The account would treat them as a live experiment with small size.
- **Always:** results are reported in full.
