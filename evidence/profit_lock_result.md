# Profit lock on the stock 3m signals: result (23 Oct 2026, evening)

**Protocol:** `profit_lock_protocol.md`, SHA-256 `a572115cd071a32a0ee137b752a5b646b611bb659fb21bbe06b1b14f142fe1d6`, registered at 15:43 before the run.
**Code:** `nfce_engine/tools/profit_lock.py`. Its walker `walk_lock` was checked on hand-made bars before the run (5 cases, all as calculated). It runs inside the same engine pass via the new `walkers` hook of `stock3m_research.trades` (defaults unchanged; engine tests 108 pass).
**Data:** 210 F&O stocks, 3m, 2022–24, current costs; 16,598 trades.

## Train 2022–24: both FAIL (Bonferroni, p < 0.025 needed)
| Exits | Win % | Gross R | **Net R** | Day-block 95% | PF | Avg win | Avg loss | ₹ (1 lot) | Exits |
|---|---|---|---|---|---|---|---|---|---|
| K4 (no lock, reference) | 46.7 | +0.047 | **−0.034** | −0.049..−0.018 | 0.94 | +0.520 | −0.519 | −28.9 L | 15:15: 11,750 · target 2,854 · stop 1,989 |
| P1 breakeven lock after +1R0 | 28.8 | +0.030 | **−0.050** | −0.062..−0.038 | 0.85 | +0.581 | −0.305 | −58.4 L | lock 6,403 · 15:15: 6,675 · target 2,105 · stop 1,410 |
| P2 half-profit trail after +1R0 | 63.1 | +0.018 | **−0.063** | −0.072..−0.053 | 0.77 | +0.199 | −0.509 | −79.1 L | lock 9,546 · 15:15: 4,803 · stop 1,410 · target 834 |

Validation and the final stage are not run.

## What it means
- **Locking profit makes these signals worse, not better.**
  - P2 wins 63% of the time, but its wins shrink to a fifth while the losses stay full size.
  - P1 turns many would-be winners into scratch trades.
- **Where the edge lives:** the little edge these entries have is in the trades that keep running to the close.
- **So the give-back on a day like 23 Oct** (+₹70,281 at 10:16 → −₹3,080) is the price of keeping runners on other days, not a fixable leak. A lock would have saved that morning and lost more over the 3 years.
- **Not adopted:** neither variant goes into the accounts.
- **What stays:** the live true-breakeven correction (a runner after T1 may not sell below the option's cost) stays as a correction of the existing "breakeven" rule.
  - It can also cut some option runners short.
  - There is no option history to measure that; the accounts will show it live.
