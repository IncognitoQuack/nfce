# 3-session paper simulation: protocol (written 19 Oct 2026, ~20:00 IST, before any result was computed)

**Sessions:** 15, 16 and 19 Oct 2026 (the last three NSE sessions). Every earlier bar is warm-up only; no trade before 15 Oct is counted.

**Universe:**
- the 50 Nifty stocks (instrument = STOCK);
- NIFTY (spot ^NSEI, heavyweight volume proxy);
- BANKNIFTY (spot ^NSEBANK, bank heavyweight volume proxy).

**Timeframes:** 5m and 15m (15m bars built from the 5m data).

**Data:** Yahoo Finance 5-minute bars (stocks carry real volume) and India VIX.
- **Heavyweights:** stocks use the Nifty list as a market-breadth input, as Pine's STOCK mode does.
- **No OI:** there is no open-interest data, so that factor drops out and the score renormalises, as in Pine.

**Expiry:** 19 Oct is the shifted Nifty weekly expiry (20 Oct is Dussehra), so `extra_expiry_dates = {2026-10-19}`. The expiry rules apply only to NIFTY; the stocks run as STOCK.

**Costs:**
- **Fee schedule:** the dated futures schedule (`nfce/costs.py`), plus 4 ticks friction per side.
- **Indices:** index lot sizes.
- **Stocks:** units = round(₹7 lakh / price), roughly a stock-futures lot, with a 0.05 tick.

**Candidate changes, fixed now** (taken from the round-1 reviews, not from these results):

| ID | Change |
|---|---|
| V0 | Base system, v2 defaults (unchanged) |
| V1 | Single exit at 2R (no 40/30/30 partials): `r1m = r2m = r3m = 2.0` |
| V2 | Lean score: only Volume and HTF factors (weights of the other 7 = 0) |
| V3 | Volume surge required as a hard filter (`req_vol = True`) |
| V4 | No entries after 13:30 (`last_entry = 1330`) |

**Selection:**
1. Rank V1–V4 by **net R per trade on 15–16 Oct** (in-sample), among variants with at least 10 trades.
2. Adopt the best one **only if** it beats V0 in-sample **and** still beats V0 on **19 Oct** (out-of-sample).
3. Either way, report every variant on every day.
4. Nothing is changed in the live system on this evidence. One out-of-sample day is far too little; a surviving change would become a registered experiment.

**Reported for each variant:**
- trades;
- win rate (net);
- gross R and net R;
- day-block 95% interval on net R;
- best and worst trade;
- exit-type counts.
