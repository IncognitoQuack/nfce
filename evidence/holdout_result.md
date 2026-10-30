# Hold-out test: result (19 Oct 2026)

**Protocol:** `holdout_protocol.md` (SHA-256 `80ff566a769ab6a1…`), frozen before this run. 28 hold-out sessions, 14 Aug – 14 Oct 2026, never simulated for P&L before. Output: `holdout.json` in the session scratchpad.

| Design | Trades | Win % (net) | Gross R | Net R [day-block 95%] | Profit factor | Positive days | Paper ₹ |
|---|---|---|---|---|---|---|---|
| H0 base | 504 | 43.8 | +0.150 | **−0.284** [−0.410, −0.177] | 0.53 | 5 / 28 | −5,65,055 |
| H1 morning entries only (≤ 11:15) | 124 | 53.2 | +0.212 | **−0.123** [−0.359, +0.074] | 0.78 | 11 / 26 | −75,668 |

**Verdict:** H1 **FAILS** the frozen criteria: net expectancy ≤ 0, the interval crosses 0, and PF 0.78 < 1.10. It is not adopted, and the live system is unchanged.

## What the 819 simulated trades (development + hold-out) establish
1. **The base system loses after costs.** The loss is clear on unseen data too: 504 hold-out trades, net −0.28R, interval entirely below 0.
2. **Trading costs are about 0.3–0.4R per trade.** They exceed any gross edge the breakout signal has.
3. **Morning entries have a small positive gross edge,** and it replicated. It was found on development data (+0.13R before costs) and appeared again on the hold-out (+0.21R before costs, 53% winners). Even so, it is not large enough to pay for futures trading costs.
4. **Tuning cannot fix this.** The cost gate halves costs but removes the edge along with them. Exit and score changes move results within noise.

## The one evidence-based lead left
The morning effect is the only finding that held up out of sample. Turning it into money would need execution costing about 0.1R or less per trade.

This is an open question, not a result: "morning NFCE breakouts executed through ITM options" fits the already registered experiment R1 (option execution measured live from real bid/ask) and could be registered as its own variant. Futures cannot do it at today's STT.
