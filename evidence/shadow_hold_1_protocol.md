# SH-1: "book small profits, hold losers to recover" — shadow protocol (registered Wed 28 Oct 2026, ~10:50 IST)

**Owner, 28 Oct 10:41:** "sell the one in profit and wait for loss one to recover". Run as a SHADOW only (owner's choice,
10:44): the six accounts and the bridge are not touched. Written before any of today's positions has closed.

## What is replayed
Every option position the six paper accounts open on 28 Oct (table `account_positions`, any status), from its entry
time to 15:15, on the recorded option ticks in `nfce_bridge/data/stream_20261028.db` (best bid = what selling gets).

## The SH-1 exit rule (per position, all lots together, no partial exits)
- `R` = entry premium − the leg's premium stop (`opt_sl` in the position state; if missing, the account's own exit
  is used and the position is reported as "no R").
- **BOOK:** sell at the first tick whose bid ≥ entry + 0.5 R ("decent profit").
- **No stop.** The underlying stop, the premium stop and the 1.5× hard stop are ignored.
- **RECOVER:** once the bid has been at or below entry − R (where the account's stop would have been), sell at the
  first later tick whose bid ≥ entry (back to the entry price).
- Otherwise sell at the last bid at or before **15:15:00**.
- Same fees as the accounts (`bridge.costs.option_fees`, 2 orders).

## Compared with
The account's actual result on the same position (its fills in `account_fills`, after fees). Reported per position,
per account, and in total: SH-1 net ₹, account net ₹, difference, and how each position exited (BOOK / RECOVER / 15:15).

## What it can and cannot say
One day is an anecdote. Whatever today shows, SH-1 goes into the accounts only after a locked history test
(2022–24 train → 2025 validation → one-shot) — registered separately tonight — and with the owner's OK, as a new
account (the 5L stays as it is). The known risk of "no stop": a loser that never recovers is held to 15:15 at full size.
