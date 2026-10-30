# Hold-out test: protocol (19 Oct 2026, ~20:40 IST, before any hold-out result was computed)

**Sessions:**
- **Development (17, already studied):** the 3 sessions of `sim3d` plus the 14 sessions of `sim250`.
- **Hold-out (28, never simulated for P&L):** the other sessions from 14 Aug to 14 Oct. Note: `sim250` ran the base system over the whole pool, but only to count trades for its stopping rule. No hold-out P&L was printed or looked at.

**Designs:** chosen from the diagnosis and development results above, before the hold-out.

| ID | Rule |
|---|---|
| H0 | Base system (reference) |
| H1 | Base + entries only until 11:15 (`last_entry=1115`), the best design on development data (net −0.146R, n = 99) |

Everything else is identical to `sim3d_protocol.md`: universe, timeframes, costs, data and engine.

**H1 passes only if, on the hold-out sessions, all of these hold:**
1. Net expectancy > 0.
2. The day-block 95% interval lower bound > 0.
3. Profit factor ≥ 1.10.
4. At least 50 trades.

A pass would make H1 a candidate for a new registered live paper test, not a change to the live system. A fail means the morning effect was noise, and it is dropped.
