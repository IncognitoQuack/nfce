# F&O stock scanner rules: protocol (20 Oct 2026, written before any result of these rules was computed)

## Why
The owner asked for:
- the day's top gainers among F&O stocks;
- stocks with unusually high volume;
- an entry with stop loss and targets for each, in both directions.

Before the bridge shows such levels, the rules behind them are tested on history at current costs, with the same staged discipline as every other study here.

## Data
- **Universe:** Upstox 5m bars, 2022-01 to 2026-07, for the 50 NIFTY-50 stocks in `hist50/`. All of them are F&O stocks.
- **Limitation:** this is a subset of the 246 F&O stocks. It is today's NIFTY-50 list, so it has survivorship bias and the results may be optimistic.

## Definitions (per stock, per day, at decision time T = the close of the bar starting T − 5 min)
- **chg:** close at T ÷ previous session close − 1.
- **rvol:** cumulative volume up to T ÷ the mean cumulative volume up to T over the previous 10 sessions. It needs 10 prior sessions.
- **Ranking:** across the stocks with data that day.

## Rules (9 configurations = 3 rules × T ∈ {10:15, 11:15, 13:15})
| Rule | Long | Short |
|---|---|---|
| **G1 gainer continuation** | top 5 by chg, if chg > 0 | bottom 5 by chg, if chg < 0 |
| **G2 volume surge** | top 5 by rvol with rvol ≥ 1.5, if close at T > day open | same list, if close at T < day open |
| **G3 reversal** | bottom 5 by chg, if chg < 0 | top 5 by chg, if chg > 0 |

## Trade management (identical for all rules; this is what the bridge would show)
- **Entry:** the open of the bar after T.
- **Risk:** R = 0.5 × ATR14 of daily bars, from previous days only.
- **Stop:** entry ∓ R.
- **Targets:** T1 = entry ± 1R (exit 1/3, stop moves to breakeven), T2 = ± 2R (exit 1/3), T3 = ± 3R (exit the rest).
- **Time exit:** at the 15:15 bar close.
- **Fill rules:**
  - The stop is checked before the targets inside a bar.
  - A gap through the stop fills at the open.
  - The entry bar is checked too.
  - An incomplete day closes at its last bar, marked as such.
- **Limits:** one trade per stock, per rule, per day.

## Costs (current, 2026)
- `futures_cost_points` with `costs.CURRENT`.
- Size: about ₹7 lakh notional per trade (units = round(700,000 ÷ entry), at the entry price).
- Orders: 1 + the number of exits.
- Friction: 0.02% of price per side.

## Stages
| Stage | Window | Survives iff |
|---|---|---|
| Train | 2022–2024 | mean net R > 0 and one-sided p < 0.05 on **day means** |
| Validation | 2025 | mean net R > 0 and one-sided p < 0.05 / k on day means (k = number of train survivors) |
| Final (one shot) | 2026-01 to 2026-07 | mean net R > 0, day-block 95% lower bound > 0, profit factor ≥ 1.10, ≥ 100 trades |

## Use of the result
- **A rule that passes all three stages:** labelled VALIDATED (historical) in the bridge's scanner alerts and paper-traded live.
- **Every other rule:** its lists and levels are still shown, because the owner asked for them, but labelled NO EDGE with its measured numbers. They are paper-traded too, so live results can be compared with the test.
- **What it is not:** none of this is a recommendation.
