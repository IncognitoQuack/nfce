# EARLY mode (first 15 minutes, 3m, F&O stocks): protocol (21 Oct 2026, ~15:45 IST, before any result)

## Why
On 21 Oct (09:57) the owner asked for signals in the first 15 minutes "to use the initial momentum". The tested rules skip those bars (`skip_open = 15`). The live stock engine now has an EARLY mode (`skip_open = 0`) for entries on bars closing 09:18–09:30, labelled untested and given half risk in the paper account. This study tests it.

## Data, signals, execution, costs
As in `stock3m_protocol.md`: the 50 NIFTY-50 stocks, 3m candles 2022-01 to 2026-10-20, single lot, T1 all out, stop first, current costs, ≈ ₹7 L notional, 0.02% friction per side. The only difference: `Params(instr="STOCK", skip_open=0)`, and only trades whose entry bar closes at 09:30 or earlier are counted.

## Variants
| Name | Rule |
|---|---|
| E0 | every early signal |
| E1 | early signals with cost share ≤ 20% |

## Stages
The same as `stock3m_protocol.md`: train 2022–24 (net R > 0, one-sided p < 0.05 on day means); validation 2025 (p < 0.05 / k); final 2026-01-01..10-20, one shot (mean > 0, day-block lower bound > 0, PF ≥ 1.10, ≥ 100 trades).

## Use
- **If a variant passes:** the EARLY signals keep their place, with the cost gate if E1 passed, and lose the "untested" label.
- **If not:** EARLY signals stay as information only, with no paper-account trades (risk scale 0).
