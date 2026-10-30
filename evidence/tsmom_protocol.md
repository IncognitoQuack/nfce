# Time-series momentum on F&O stock futures, weekly (registered 22 Oct 2026, evening, before any result)

**Why:**
- **The cost problem:** tonight's studies showed that intraday 3-minute trades move too little to pay their costs. Over weeks, moves are many times larger than the same costs.
- **The evidence base:** time-series momentum is among the most widely documented effects in published market research. Hold an asset in the direction of its own past trend, sized by its volatility (Moskowitz, Ooi & Pedersen 2012, and many later studies).
- **Not tested here before:** never on Indian F&O stocks in this project.

**Data:**
- **Prices:** Upstox daily candles, 2016-10-24 → 2026-10-21 (`~/Downloads/nfce_data/daily`, `ops/pull_daily.py`). Split-adjusted by the source, which was checked for gaps.
- **Universe:** today's 213 F&O stocks.
- **Survivorship bias (stated now):** these are the stocks still in F&O today. That flatters long positions; the result is reported with this caveat.

**Corporate actions:**
- A week whose holding period contains an overnight gap beyond −30% or +40% (7 found: demergers and listing glitches) earns 0 for that stock, with no cost.
- A stock trades only after it has L + 60 trading days of history.

**Rule (decided at each week's last trading day close, using closes up to that day only):**
- **Signal:** s = sign of the stock's return over the past **L** trading days (close to close).
- **Size:** weight w = s × min(1% / σ, 3), where σ is the stock's daily return standard deviation over the past 60 days. Equal risk per stock, capped at 3× notional.
- **Execution:** enter or adjust at the **next trading day's open**; hold to the next rebalance's next-day open (open-to-open returns).
- **Portfolio:** the weekly return is the average of w × r over the active stocks. Equal risk across stocks; returns are per unit of capital.

**Costs (measured, not assumed):**
- **Fees:** current NSE futures fees 3.2 bp per side on average (STT 0.05% on the sell side, exchange, SEBI, stamp, GST, brokerage; `bridge/costs.py`).
- **Spread:** half of the median stock-future spread measured live on 22 Oct (8.75 bp), about 4.4 bp.
- **Per side:** **c = 8 bp**, charged on turnover, c × Σ|w_t − w_t−1|.
- **Monthly roll:** 2c × Σ|w| in every week containing the monthly futures expiry (last Tuesday).
- **Stress:** 12 bp per side (1.5×) also reported.

**Tests (one family, Bonferroni over 3):**

| Config | Lookback L |
|---|---|
| TS60 | 60 days (about 3 months) |
| TS120 | 120 days (about 6 months) |
| TS250 | 250 days (about 12 months) |

**Pass (each config, each stage):** all four of
1. mean weekly net return > 0;
2. a 4-week-block bootstrap 95% interval of the mean above 0;
3. a one-sided t-test on weekly returns p < 0.0167;
4. annualised net Sharpe ≥ 0.5 (at 8 bp).

**Stages:**

| Stage | Period |
|---|---|
| Train | 2019-01-01 → 2024-12-31 |
| Validation | 2025 (only configs that pass train) |
| Final, one shot | 2026-01-01 → 2026-10-21 (only configs that pass validation) |

The train period is longer than the 2022–24 convention because weekly decisions need more weeks: 2019–24 is about 310 weeks, and includes the 2020 crash.

**Reported at each stage that is run:**
- weekly mean, volatility and Sharpe; maximum drawdown; % of positive weeks; turnover;
- the 12 bp stress;
- the long and short halves separately;
- two benchmarks: an equal-risk long-only portfolio of the same stocks, and NIFTY buy-and-hold.

**What a pass means:**
- **A rule that held on unseen years after measured costs.** It would start as a live paper book (weekly futures positions, priced at real quotes) before any further step.
- **Not live money.** It is not a decision to trade real money; that stays the owner's.
