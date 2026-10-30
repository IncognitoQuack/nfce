# Same-direction cap: historical replay (registered 22 Oct 2026, 13:40 IST, before running it)

**Asked by:** the owner (22 Oct): "Replay the same-direction cap on history tonight ... show me the result, but don't add it yet." The cap is the same rule as V3 in `live_variants_protocol.md`.

**Why:** at 12:12–12:18 on 22 Oct, 10 same-direction signals fired within 6 minutes and were stopped together.

## Data and trades
- **Trades:** the stock 3-minute NFCE trades of `stock3m_protocol.md`: 50 NIFTY-50 stocks, Upstox 3m, current costs, one lot of about ₹7 L notional, all out at T1, stop first. The code is `nfce_engine/tools/stock3m_research.py` unchanged, except that each trade row also records its entry time.
- **Base:** V0, every signal (cost share unrestricted).

## Rule
- **Cap:** in time order across all stocks, a trade is skipped if 2 trades of the same direction were already **taken** with entry times in the previous 30 minutes (the window includes 30 minutes back, exclusive).
- **Same entry time:** order by symbol name.

## Stages
- **Train:** 2022–24.
- **Validation:** 2025, run only if train passes.
- **2026:** not used (kept back).

## Reported for V0 and CAP (every number, whatever it shows)
- trades and the share skipped;
- win %;
- mean net R per trade, with a day-block 95% interval;
- **daily total net R:** mean, worst day, 5th percentile;
- maximum drawdown of cumulative net R;
- total net R;
- rupees at one lot.

## Pass rule (fixed now)
The cap PASSES a stage if all three hold:
1. the worst day and the maximum drawdown both improve by at least 25%;
2. the 5th-percentile day improves;
3. mean net R per trade is no worse than V0 by more than 0.02R.

Passing means **less risk, not profit**. The base strategy loses after costs (−0.34R), and a cap that skips trades cannot by itself make it profitable. The result is shown to the owner; nothing is added live without the owner's go-ahead.
