# R5 — Williams 3-day swing breakout on NIFTY: protocol (20 Oct 2026, ~02:05 IST, before its 2026 data was examined)

## Why this experiment exists
Under `external_protocol.md`, S4 NIFTY did **not** pass validation:
- 2025: +0.059R per trade, PF 1.23, on 77 trades, but one-sided p = 0.26 (the bar was p < 0.05).
- So by that protocol it stops.

It was, however, the only rule positive at **current** costs in most years: 2022 +0.025R, 2023 −0.004R, 2024 +0.081R, 2025 +0.059R. Its Jan–Jul 2026 data has not been looked at for this rule. R5 registers a new, separate test now, so the deviation from the original protocol is explicit and before the fact.

## Rule (unchanged from S4; `nfce_engine/nfce/research2.py: williams_dsr`)
| | |
|---|---|
| Range | DSR = max(\|H(t−3) − L(t−1)\|, \|H(t−1) − L(t−3)\|) from daily bars |
| Entry levels | buy stop at open + 0.5 DSR; sell stop at open − 0.5 DSR; active on bars 09:20–14:30; first trigger only; a bar touching both levels means skip the day |
| Stop, target, exit | stop = today's open; target = entry ± 2 DSR; exit at the 15:25 close; one trade a day |
| Instrument | NIFTY spot as a futures proxy |
| Costs | current costs (1 lot, 2 orders, 4 ticks per side) |

## Test A — historical hold-out, one shot
- **Window:** Jan–Jul 2026, run exactly once, with `tools/external_run.py --stage final --configs "S4 NIFTY"`.
- **PASS iff all hold:**
  1. net R > 0;
  2. day-block 95% lower bound > 0;
  3. PF ≥ 1.15;
  4. ≥ 20 trades.
- **Multiple testing:** 22 configurations were screened, so a PASS is still weak evidence.

## Test B — live forward paper test (whatever Test A shows, unless A fails clearly)
- **Runs:** every session from 21 Oct 2026, the same rule on the day's 5m NIFTY bars, logged after the close.
- **PASS:** ≥ 60 trades, net R > 0, one-sided p < 0.05.
- **Use:** only after B passes would R5 be a candidate for small real-money trading, and that is the owner's decision.
