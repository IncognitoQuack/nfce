# SMART-EXIT-2: the owner's rule "book a decent profit, exit the moment it goes into a small loss" (registered Wed 28 Oct 2026, ~17:15 IST, before any run)

**Owner, 28 Oct evening:** "if you just see decent profit … sell it … and dont take loss … sell it as soon as it touches the
loss (or at least is in very very less loss) and make money … doing this multiple times." This is NOT SMART-EXIT-1:
there the stop stayed at 1R (S1/S2) or was removed (S5). Here the stop is TIGHT.

## Trades
Identical to `smart_exit_1_protocol.md`: the stock 3m NFCE signals, ~210 F&O stocks, current costs, one futures lot of
~₹7 L, R0 = the signal's own risk; the same walk convention (3-min bars; within a bar the stop is checked before any
profit exit; gaps fill at the open; a moved level applies from the next bar; 15:15 close). Net R in units of R0.

## Variants (family of 4, Bonferroni: each needs one-sided p(day) < 0.0125)
- **T1:** book everything at +0.5 R0; stop at −0.25 R0.
- **T2:** book everything at +0.3 R0; stop at −0.15 R0.
- **T3:** book everything at +0.5 R0; stop at −0.5 R0.
- **T4:** book at +0.5 R0; stop at −0.25 R0; once +0.25 R0 has been reached, the stop moves to the entry.

## Pass (each variant): net R > 0 after costs, day-block 95% CI above 0, p(day) < 0.0125. Train 2022–24; validation
2025 and the one-shot 2026 only for variants that pass train.

## Known limitation (stated before the run)
3-minute bars cannot see the order of the high and the low inside a bar. With stops this tight, many bars touch both
levels; the convention counts them as stops (conservative). The share of such "both-touched" bars is reported. A pass
here would still need a tick-level check (the stream records ticks from 28 Oct) before any use.

## Use
A full pass: a new paper account, with the owner's OK. A fail: reported plainly, not re-tuned.
