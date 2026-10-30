# XM (market-neutral 12-1 momentum) on an untouched older sample, 2006–2016 (registered 25 Oct 2026, evening, before downloading or seeing any of this data)

**Why:**
- On 2019–24, XM made +0.52% a month after costs (Sharpe 0.63, corr with NIFTY −0.18) but missed its bar (p 0.066 vs 0.0167; `xs_result.md`).
- The fair next test is data never used by this project: the decade before.

**Rule:** exactly XM of `xs_protocol.md`, code unchanged (`tools/xs.py`: `cross_section`, `mom_score`, `months`):
- monthly; rank by the 12-1 return;
- long the top 20%, short the bottom 20%;
- weights ∝ 1/σ, half the risk on each side; next open to next open;
- costs 8 bp per side on turnover plus the monthly roll (stress 12 bp).

**Data:**
- **Prices:** Upstox daily candles for the same symbols (today's 213 F&O stocks), plus NIFTY, for 2006-10 → 2016-10 (`ops/pull_daily.py` with an explicit date range → `~/Downloads/nfce_data/daily_2006/`).
- **Universe:** stocks enter only once they have 260 days of history, as before. Fewer stocks are expected in the early years: they had not listed yet.
- **Requirement:** at least 30 stocks ranked at every decision. Months with fewer are skipped (and counted).

**Stated in advance:**
- **Survivorship bias:** the universe is today's F&O list, so stocks that failed after 2006 are missing. This flatters the long side.
- **Costs:** the cost level is today's, not 2006's. Costs were higher then, so this flatters the result too.
- **So:** a pass here is necessary, not sufficient. A fail is decisive.

**Test period:** decisions from 2007-11 onward (once the first stocks have 260 days of history) to 2016-09.

**Pass:** a single confirmation test, so all four of
1. mean net monthly return > 0;
2. a 3-month-block bootstrap 95% CI above 0;
3. a one-sided t-test p < 0.05;
4. annualised net Sharpe ≥ 0.5.

**Reported:** every number; the 12 bp stress; the long and short legs; the correlation with NIFTY; the number of stocks ranked per month.

**Use:**
- **A pass:** XM becomes a candidate for a monthly paper book, live from the next month-end, and is reported to the owner. Still no real money.
- **A fail:** XM is closed.
