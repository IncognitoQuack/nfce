# SMART-EXIT-2: result (train 2022–24, run 28 Oct 2026, ~17:20–17:28 IST)

**Protocol:** `smart_exit_2_protocol.md`, SHA-256 `9fe876ea0b911df5b1a1fc577bed00dd9417c1f893c6cfa2fb45c1bcfe0947a0`,
hashed 17:12 before the run. **Code:** `nfce_engine/tools/smart_exit2.py`, checked on 7 hand-made cases first.
**Data:** 210 F&O stocks, 3-minute bars, 2022–24, current costs; 16,598 trades.

## Verdict: all four variants FAIL train. Not re-tuned; validation and final not run.

| Rule | Win % | Gross R | **Net R** | PF | Avg win | Avg loss | Exits | Both-touched bars |
|---|---|---|---|---|---|---|---|---|
| T1: book +0.5R, stop −0.25R | 27.7 | −0.015 | **−0.335** | 0.23 | +0.225 | −0.550 | stop 11,382 · book 5,209 | 4.4% |
| T2: book +0.3R, stop −0.15R | 14.2 | −0.032 | **−0.352** | 0.07 | +0.094 | −0.426 | stop 12,229 · book 4,363 | 18.4% |
| T3: book +0.5R, stop −0.5R | 42.8 | −0.014 | **−0.335** | 0.33 | +0.225 | −0.755 | book 8,054 · stop 8,525 | 1.4% |
| T4: T1 + stop to entry after +0.25R | 23.3 | −0.018 | **−0.339** | 0.20 | +0.225 | −0.510 | stop 9,788 · book 4,391 · scratch 2,413 | 6.1% |
| (the accounts' exits, SMART-EXIT-1 "LIVE") | 45.8 | +0.071 | −0.250 | 0.70 | | | | |

## What it means
- **With a tight stop, the small loss is touched before the small profit most of the time.** T1 hit its stop 2.2× as often as its target.
- **Every variant is negative even BEFORE costs** (gross −0.014 to −0.032R): the rule loses on price movement alone, and then pays ~0.32R a trade in costs.
- **It is not a bar-data artefact.** If every "both-touched" bar (where 3-minute bars can't tell the order) had counted as a win, T1's gross would rise by about +0.033R, to about +0.02R. That is still far below the 0.32R cost.
- **The owner's observation on 28 Oct ("6/7 in profit" on the Risk tab) came from the desk's sign bug**, fixed at 11:04. At ~10:40 every open position was actually losing.
- The real pattern of the day was positions briefly in profit and then stopped. That is exactly what both tests measured over 16,598 trades.
