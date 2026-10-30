# Five strategy paper accounts (registered 22 Oct 2026, evening, before the 23 Oct open)

**Asked by:** the admin (S chat, 14:58): "prepare 5 accounts ... to test different strategy ... if you have a better idea then go with that". The better idea was accepted as offered: five accounts that differ by **strategy**, not size. Each starts with **₹5,00,000** and sees the same live signals: NIFTY/SENSEX engine signals at full risk, stock 3-min signals at 0.25× risk.

**Shared rules** (as the existing 5L account, `bridge/account.py`), unless a row below says otherwise:
- buy the 1-ITM option; risk 1% of equity per trade, sized from the stop;
- cost gate 25%; one position per underlying; at most 60% of equity in premium;
- at most 4 open; no entry after 14:45; 3% daily loss limit;
- 30-minute pause after 3 losses in a row;
- whole-lot exits 40/30/30 on the underlying, breakeven after T1;
- premium and hard stops; 15:15 square-off.

| Account | Strategy | What differs |
|---|---|---|
| **5L** | base | Nothing: the account that has run since 21 Oct |
| **CONC** | concentrated | 5% risk per trade, stock signals at full size (no 0.25×); at most 3 entries a day and 3 open; daily loss limit 10%; up to 90% of equity in premium. "A few big trades" |
| **WIDE** | wide stop | The underlying stop at 2× the signal's distance; T1/T2/T3 at 2/4/6× (the same R multiples of the wider R); the premium stop at 2× the premium distance; so half the lots for the same risk |
| **CONF** | confirmation | No entry at the signal. Wait up to 15 minutes for the underlying to trade 0.5R beyond the entry in the signal's direction, then buy at the live ask. Levels as signalled, so 1.5R to the stop; the premium stop at 1.5× the premium distance from the new ask. Not confirmed in 15 minutes, or after 14:45: no trade |
| **CLUS** | cluster-safe | At most 2 new entries of the same direction in any 30 minutes; and a 30-minute time stop: an open position that has not reached T1 is sold at the bid 30 minutes after entry |

**Reporting:**
- Only the 5L account sends trade messages. The other four are quiet: they show in `/account`, the daily report and the ledger.
- Each day, every account is reported side by side, with every number, losses included.

**Judging (fixed now):**
- No account is called better before **20 sessions**.
- At 20 sessions, compare each account with 5L on:
  - daily equity change (day means, block bootstrap);
  - worst day;
  - maximum drawdown.
- These are paper results on live signals that test negative historically. None of them is expected to be profitable; the comparison shows which handling loses least or (if any) gains.
