# SMART-EXIT-1: result (train 2022–24, run 28 Oct 2026, 13:40–13:48 IST)

**Protocol:** `smart_exit_1_protocol.md`, SHA-256 `b62e3b9705a91ff1cf95755c7916a75cf8e2e66b53360cfe20f97e4a55d46adc`,
hashed 13:37 before the run. **Code:** `nfce_engine/tools/smart_exit.py` (walker checked on 10 hand-made cases first;
one bug in S5's recovery check was found and fixed by those cases, before the run).
**Data:** 210 F&O stocks, 3-minute bars, 2022–24, current costs; 16,598 trades.

## Verdict: all five variants FAIL train. Validation and final are not run.

| Exits | Win % | Gross R | **Net R** | 95% CI | PF | Avg win | Avg loss | Worst trade | Worst day | ₹ (1 lot ≈ ₹7 L) |
|---|---|---|---|---|---|---|---|---|---|---|
| K1 (reference: stop 1R, target 1R) | 51.5 | +0.051 | **−0.270** | −0.290..−0.249 | 0.66 | +0.675 | −1.273 | −3.87R | −22.7R | −93.9 L |
| LIVE (reference*) | 45.8 | +0.071 | **−0.250** | −0.275..−0.224 | 0.70 | +0.821 | −1.153 | −3.87R | −23.9R | −84.1 L |
| S1 book at +0.5R | 59.3 | +0.014 | **−0.307** | −0.322..−0.293 | 0.43 | +0.223 | −1.078 | −3.87R | −20.9R | −111.8 L |
| S2 book at +0.3R | 40.3 | −0.002 | **−0.322** | −0.334..−0.311 | 0.20 | +0.094 | −0.603 | −3.87R | −21.3R | −120.3 L |
| S3 trail half the best after +0.5R | 43.5 | +0.036 | **−0.284** | −0.303..−0.266 | 0.53 | +0.457 | −0.856 | −3.87R | −22.7R | −99.5 L |
| S4 S1 + book any profit after 30 min | 55.8 | +0.014 | **−0.306** | −0.321..−0.293 | 0.40 | +0.217 | −0.967 | −3.87R | −19.8R | −112.5 L |
| S5 owner's rule: +0.5R, no stop, hold to recover | 59.4 | −0.014 | **−0.334** | −0.361..−0.308 | 0.40 | +0.223 | −1.149 | **−43.96R** | **−70.0R** | −123.0 L |

\* LIVE is approximate: it keeps the stop at entry after T2, while the accounts move it to T1 (the research/live drift
that MASTER_SYSTEM_PLAN.md L3 removes). It is a reference, not a test.

## The owner's observation is right; the conclusion is not
- **Trades do go into profit:** 68% of all trades reached +0.5R at some point, and 51% reached +1R.
- **A third of the losers had first been at +0.5R** (53% had been at +0.3R).
- **But booking it early loses more money.** Costs are about 0.32R a trade (gross − net):
  - a +0.3R booking nets about zero, which is why S2 "wins" only 40% after costs;
  - a +0.5R booking nets about +0.2R, while the stopped trades still cost about −1.1R.
- **The exits only move the money around.** These entries' gross edge is only +0.01 to +0.07R, below their costs, so no exit rule can turn them profitable.
- **S5 (no stop) is the worst:**
  - the most costly overall;
  - one trade lost 44R;
  - one day lost 70R (about 70× a normal stop).

  "Wait for recovery" works most of the time and is ruinous the rest of the time.

## What follows
- None of S1–S5 goes into an account. Per the owner's choice (13:55) they would have run as shadow books first; with a
  train FAIL they are not promoted. The SH-1 shadow for today is still scored tonight, for the record.
- The real problem is entry quality vs costs, not exits. The next registrations should therefore target cost or entry:
  - the CLUS-style 30-min time stop (it halved two losses on 28 Oct);
  - the open-risk budget (a risk control);
  - fewer, cheaper trades (cost share ≤ 15%);
  - the regime filter;
  - the signal-context protocol after ~20 sessions.
