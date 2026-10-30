# Results days and the stock 3m signals (registered 23 Oct 2026, evening, before joining the calendar with any trade)

**Why:** the admin (S chat, 23 Oct 11:13) asked to consider news, especially results, "as that also changes the direction of the market/stock".

**Calendar:**
- **Source:** NSE's public board-meeting list, 2022-01 → 2026-10 (`ops/pull_results_calendar.py` → `~/Downloads/nfce_data/results_calendar.csv`).
- **Size:** 46,346 meetings, 40,252 about financial results; 211 of the 213 F&O stocks covered.

**Event window of a stock:** its results board-meeting date D, and the next trading day D+1. Results often come out late on D, so the reaction is often on D+1.

**Trades:** the stock 3m NFCE trades already computed tonight (210 F&O stocks, current costs):
- **V0:** the live exits;
- **K4:** the best exits found.

The trades are not re-run; they are only split by the calendar.

**Test, train 2022–24, for V0 and K4:**
- **Compare:** trades whose entry day is in the stock's event window (E) vs all other trades (N).
- **Reported:** n, win %, net R, the standard deviation of net R (risk), and the worst trades.
- **H_R** (the decision test): E has lower mean net R than N, one-sided. A day-block bootstrap of the difference (5,000 resamples, seed 0), p < 0.05.

**Use (fixed now):**
- **If H_R holds on train AND on 2025 (one look)** for the trades the live accounts take (V0), the accounts skip a stock in its event window.
  - It is a risk control, not a profit claim.
- **Whatever the result, the alerts show a "📰 results" flag** for stocks in their event window, from the live NSE event calendar, so a person can judge.
- **If H_R fails:** no skip rule; the flag only.
