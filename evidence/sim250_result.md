# Random-day paper simulation, 260 trades: result (19 Oct 2026)

**Protocol:** `sim250_protocol.md` (SHA-256 `280d1f1f97555681…`, frozen before running). **Tool:** `nfce_engine/tools/sim250.py`, seed 20261019.
**Full output:** `sim250.json` in the session scratchpad (SHA-256 `74fd2218bcb7eb4b…`).
**Sessions (random order, stopped at ≥ 250 base trades):** 14 Aug, 17 Aug, 25 Aug, 26 Aug, 2 Sep, 8 Sep, 9 Sep, 11 Sep, 16 Sep, 17 Sep, 28 Sep, 5 Oct, 7 Oct, 8 Oct 2026.

| Variant | Trades | Win % (net) | Gross R | **Net R** [day-block 95%] | Profit factor | Positive days | Paper ₹ |
|---|---|---|---|---|---|---|---|
| V0 base | 260 | 40.0 | +0.050 | **−0.323** [−0.596, −0.040] | 0.51 | 2 / 14 | −2,51,913 |
| V2 lean volume+HTF | 228 | 38.2 | −0.029 | **−0.411** [−0.572, −0.244] | 0.41 | 2 / 14 | −4,03,179 |

**Base system detail:**
- **Exits:** 107 stops, 66 square-offs, 64 breakeven/trail, 23 T3.
- **Instruments:** 13 index trades; the rest are stocks.
- **Best / worst:** APOLLOHOSP 15m short +1.79R; WIPRO 5m short −2.40R (gapped past the stop).
- **Net R by day:** −0.67, −0.33, −0.62, +0.09, −0.76, −0.36, −0.21, −0.82, −0.57, −0.37, −0.33, −0.86, −0.67, +0.47.

**Verdict:**
- **Owner's posting rule (win rate ≥ 90%):** not met (40%), so nothing was posted.
- **Research verdict:** **fail.** Expectancy is negative, and its 95% interval lies entirely below zero.
- **Costs are the decisive factor:** before costs the base is about break-even (+0.05R per trade); fees and friction take about 0.37R per trade.
- **V2:** this second out-of-sample check confirms it. V2 is worse than the base, so it is dropped as a candidate.
- **No change to the live system.**
