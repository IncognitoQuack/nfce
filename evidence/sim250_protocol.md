# Random-day paper simulation, ~250 trades: protocol (19 Oct 2026, ~20:15 IST, before any result)

**Same as `sim3d_protocol.md`:**
- the universe (the 50 Nifty stocks plus NIFTY and BANKNIFTY spot with proxy volume);
- the 5m and 15m timeframes;
- the data (Yahoo 5m, 24 Jul – 19 Oct 2026);
- the costs (dated futures fees plus 4 ticks per side);
- the engine (v2 defaults).

**Days:**
- **Pool:** sessions 16 to 57 of the 60 available, i.e. 14 Aug – 14 Oct. The first 15 are indicator warm-up; the last 3 were already used in `sim3d`.
- **Draw:** random order with seed `20261019`.
- **Stopping rule:** take sessions in that order until the **base** system has at least 250 trades. The rule depends only on the trade count, never on profit or loss.
- **Expiry dates:** the calendar rule only. No holiday-shifted expiries are added for these days, which is a small, stated limitation.

**Variants:** none are tuned; both were fixed before this run.

| ID | Rule |
|---|---|
| V0 base | Unchanged system |
| V2 lean volume+HTF | Fixed in `sim3d`. It failed its one out-of-sample day; this run is its second, larger out-of-sample check |

**Measures:**
- win rate (net of costs);
- **expectancy** (net R per trade), the measure that decides;
- profit factor;
- day-block 95% interval;
- results by day and by exit type;
- the best and worst trade.

**Success, defined before running:**
1. **The owner's posting rule** is a win rate of 90% or more. Below that, nothing is posted to Telegram.
2. **The research verdict** additionally requires a positive expectancy whose day-block interval lies above 0. A win rate alone is not success.

**No re-tuning on these results.** Whatever happens is reported, here and in `sim250_result.md`.
