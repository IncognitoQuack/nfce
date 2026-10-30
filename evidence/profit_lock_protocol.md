# Profit lock on the stock 3m signals (registered 23 Oct 2026, evening, before any run)

**Why:**
- On 23 Oct the six paper accounts peaked at +₹70,281 (10:16) and closed at −₹3,080.
- Open profit on the runners rode all the way back (`LIVE_DAY_2026-10-23.md`).
- Question: does locking in open profit help over years, or does it only cut winners short?

**Trades:**
- **Entries:** the same entries as `wide_stop_protocol.md` (stock 3m NFCE signals, about 210 F&O stocks, current costs, one lot of about ₹7 L).
- **Base exits:** **K4**, the best exits found (stop and target at 4 × R0, R0 = the signal's own risk; −0.034R on 2022–24).
- **Units:** results are per K4 risk (4 × R0), comparable with `wide_stop_result.md`.

**Variants (added to K4):**
- **P1, breakeven lock:** once the bar's favourable extreme has reached +1 × R0, the stop moves to the entry price.
- **P2, half-profit trail:** once the favourable excursion reaches +1 × R0, the stop trails at entry + side × 0.5 × (best favourable excursion so far).
  - It only ratchets towards profit, never back.

**Walk (same convention as V0/K4):**
- **Within a bar:** the stop is checked before the target; a new stop level applies from the next bar.
- **Gaps:** a gap beyond the stop or target fills at the bar's open.
- **End of day:** an open trade exits at the close of the bar that closes at 15:15.

**Family:** two tests, Bonferroni, so each needs one-sided p(day) < 0.025.

**Pass (each variant, each stage):** all three of
1. net R per trade > 0 after costs;
2. a day-block 95% interval above 0;
3. p(day) < 0.025.

**Stages:**
- **Train:** 2022–24.
- **Validation:** 2025, only for variants that pass train.
- **Final:** a one-shot 2026 test (to 2026-10-20), only for variants that pass validation.

**Reported:** every number. Also: how much each variant changes the average win, the average loss and the share of trades stopped in profit.

**Use:**
- **A pass:** goes into the paper accounts as an exit rule.
- **A fail:** reported; the live true-breakeven correction stays regardless (it is a bug fix, not a strategy).
