# CAL-1: result (train 2006-10-23 → 2015-12-31, run 28 Oct 2026, ~21:25 IST)

**Protocol:** `cal_1_protocol.md`, SHA-256 `2e2271321a492c885d2cac13dfbd3e19dd1050201c0325d48c2b3b23bcb60079`,
hashed 21:15 before any result. **Code:** `nfce_engine/tools/cal_1.py`, trade dates checked on a hand-made calendar
first. **Data:** NIFTY daily, 4,934 sessions 2006–2026, 285 holidays inferred.
**Costs:** 10 bp round trip at the current charges (incl. 4 bp slippage), plus 6.2%/yr futures carry.

## Verdict: both FAIL train (narrowly). Validation and final are NOT run, per the protocol.

| Test | n | Win % | Gross bp/trade | **Net bp/trade** | 95% CI (bootstrap) | p (one-sided) | Years positive | Worst trade |
|---|---|---|---|---|---|---|---|---|
| C1 turn of the month (close −2 → close +3) | 110 | 62.7 | +70.1 | **+48.4** | −10.4 .. +106.6 | 0.053 | 7/10 | −836 bp |
| C2 pre-holiday (1 day) | 120 | 57.5 | +32.6 | **+19.1** | −5.8 .. +44.0 | 0.068 | 9/10 | −631 bp |

Pass needed: net > 0 **and** CI above 0 **and** p < 0.025 (two tests, Bonferroni).

## What it means
- **The most promising result in this project so far, and still not proof.**
  - Both effects are positive after costs on 2006–2015, in line with the published Indian studies.
  - Neither is distinguishable from luck at the level the protocol required. A 10-year sample of ~110 monthly trades is too small for a +48 bp mean with this much spread; one bad month costs −836 bp.
- **Not re-tuned, not re-run on later years.**
  - Running 2016–2026 now, after seeing this, would be the garden of forking paths that produced every fake edge here before.
  - A future test needs a new registration with a design fixed in advance, for example the pooled 20-year forward record from now on.
- **Not added to any account.** For the record: if the owner chooses to try it by hand in the MAN account (his own account, not a test), the next TOM window would be buy at the close of Thu 29 Oct 2026 (day −2 of October), sell at the close of Wed 4 Nov 2026 (day +3). This is stated as unproven.
