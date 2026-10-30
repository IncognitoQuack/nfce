# G20 "guarded" paper account (registered Wed 28 Oct 2026, ~17:40 IST, before its first session on 29 Oct)

**Owner, 28 Oct evening:** a new ₹20 L paper account, "any setup you think will make profit", aiming at ₹50,000 on
29 Oct. **Stated before any data: no rule set measured so far makes money after costs.** That includes every exit idea
tested on 28 Oct: SMART-EXIT-1 (5 variants), SMART-EXIT-2 (4 tight-stop variants), and the SH-1 shadow. A
+₹50,000 day (+2.5%) is not an expected outcome of this account. A loss is about as likely as a gain, with costs
tilting it negative. G20 is the account with the most risk controls that the evidence supports; it is not an edge.

## Rules
The base account's rules (`bridge/account.py`), unchanged:
- 1-ITM options; 1% risk per trade, stock signals at 0.25×;
- at most 4 open; no entry after 14:45; 3% daily loss limit;
- one position per underlying; ≤ 60% of equity in premium;
- the loss-streak pause; premium and hard stops;
- 40/30/30 exits; breakeven after T1; DG; 15:15 square-off.

Plus three controls, each chosen from 28 Oct's live record (anecdote, stated as such):
1. **Time stop:** a position not at T1 within 30 minutes is sold (as CLUS). On 28 Oct it cut every shared losing trade: SENSEX PE −2,383 vs −4,623; ITC −679 vs −1,454; SENSEX CE −4,056 vs −5,879. It also cut RELIANCE short.
2. **Cost gate 15%** (base 25%): a round trip may cost at most 15% of the trade's risk. Costs (~0.32R/trade) are what every failed test lost to.
3. **No index entry without a fresh futures quote:** on 28 Oct 13:48 a SENSEX signal whose own live check said NO_DATA was entered by 3 accounts and lost ₹11,517.

Capital ₹20,00,000, name G20 (`ACCOUNTS=…,G20:2000000:guarded`). Quiet (no trade messages of its own), like the five
strategy accounts.

## How it is judged
- Daily, after costs, next to the base account 5L on the same signals.
- A one-day result is **not** evidence either way.
- The registered verdict comes after **20 sessions**, like the other strategy accounts (`strategy_accounts_protocol.md`).
- Its controls (time stop, cost gate, NO_DATA skip) each still need their own locked history test before going into the 5L or any other account.
