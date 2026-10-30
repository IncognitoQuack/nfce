# SMART-EXIT-1: take profit early, cut loss smartly (registered Wed 28 Oct 2026, ~13:45 IST, before any run)

**Why (owner, 28 Oct 13:30):** "develop a dynamic smart algo which sells on profit even if not on target and also
avoids loss". On 28 Oct several positions showed open profit before they were stopped out (SENSEX 72700 PE: 402.15 →
448 at 10:21 → stopped at 288.50; TITAN 4300 PE: 118.35 → 122.2 at 10:22 → stopped at 108.95). (The desk's "6/7 in
profit" at ~10:40 was a sign bug, fixed 11:04; it is not part of the evidence.)

**Question:** over years, does selling early on a small profit — or holding a loser for recovery — make more money
after costs than the current exits, or does it only raise the win rate?

## Trades
- **Entries:** the stock 3m NFCE signals, about 210 F&O stocks (`tools/stock3m_research.trades`), current costs,
  one futures lot of about ₹7 L, `R0` = the signal's own risk. Same entries as `profit_lock_protocol.md`.
- **Walk convention (as K4/P1/P2):** 3-minute bars; within a bar the stop is checked before any profit exit
  (conservative: small targets that a bar both touches and stops count as stops); a gap beyond a level fills at the
  open; a level that moves applies from the next bar; end of day = the close of the bar closing 15:15.
- **Units:** net R per trade with R = R0 (the signal's risk), after costs.

## References (reported, not tested)
- **K1:** stop 1 R0, target 1 R0 (the original exits).
- **LIVE:** what the accounts do, on futures: stop 1 R0; 40% at T1 (+1 R0), then the stop moves to entry; 30% at
  T2 (+2 R0); the rest at T3 (+3 R0) or 15:15.

## Variants (the family: 5 tests, Bonferroni, each needs one-sided p(day) < 0.01)
- **S1 quick book +0.5R:** sell everything at +0.5 R0; stop 1 R0; else 15:15.
- **S2 quick book +0.3R:** sell everything at +0.3 R0; stop 1 R0; else 15:15.
- **S3 dynamic trail:** stop 1 R0; once the best favourable excursion reaches +0.5 R0, the stop ratchets to
  entry + side × 0.5 × best (never back); target 3 R0; else 15:15.
- **S4 time-aware book:** S1, plus: from 30 minutes after entry, sell at the first bar close that is in profit
  (any amount above the entry); else stop/15:15.
- **S5 hold to recover (the owner's SH-1 rule on futures):** sell everything at +0.5 R0; NO stop; once the price has
  been at or beyond −1 R0, sell at the first later bar whose favourable extreme is back at the entry (fill at the
  entry); else 15:15.

## Pass (each variant, each stage): all three of
1. net R per trade > 0 after costs;
2. a day-block 95% interval above 0;
3. one-sided p(day) < 0.01.

## Stages
- **Train:** 2022–24. **Validation:** 2025, only for variants that pass train. **Final:** one-shot 2026 (to
  2026-10-20), only for variants that pass validation.

## Also reported (descriptive, no pass/fail)
- For the K1 trades: the share that reached +0.3 / +0.5 / +1 R0 of favourable excursion before exiting, and the
  share of K1 *losers* that had first been at +0.3 / +0.5 R0 ("profit given back").
- Every variant: win %, average win, average loss, worst single trade, worst day, exit-reason counts.

## Use
- **A pass (all three stages):** becomes a new 7th paper account (the 5L and the five registered accounts stay as
  they are), with the owner's OK.
- **A fail:** reported plainly. A variant that fails train is not re-tuned; a new idea needs a new registration.
