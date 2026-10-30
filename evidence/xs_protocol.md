# Three profit-rule candidates that trade rarely and do not depend on market direction (registered 25 Oct 2026, evening, before any result)

**Why:**
- Thirteen tests so far: intraday edges are smaller than costs.
- The one train pass (TS250) was bull-market beta.
- So these candidates trade at most weekly, and the two stock rules are **market-neutral**: equal risk long and short, so the market's direction cancels out.

**Data:**
- **Prices:** Upstox daily candles 2016-10 → 2026-10 (`~/Downloads/nfce_data/daily`), split-adjusted by the source.
- **Universe:** today's 213 F&O stocks.
- **Survivorship bias, stated now:** these are the stocks that survived into today's F&O list.
- **Corporate-action gaps:** handled as in `tsmom_protocol.md` (a holding period with an overnight gap beyond −30%/+40% earns 0).

**Costs:**
- **Stock futures:** 8 bp per side on turnover, plus the monthly roll, exactly as in `tsmom_protocol.md` (measured on 22 Oct); stress 12 bp.
- **NIFTY futures:** 4 bp per side.

**XM, cross-sectional momentum** (monthly):
- **Decision:** at the last trading day of each month.
- **Ranking:** stocks with at least 260 days of history, by the return from 252 to 21 trading days back (12-1 momentum).
- **Positions:** long the top 20%, short the bottom 20%. Weights ∝ 1/σ (60-day daily vol), scaled so the long book and the short book each carry half the risk.
- **Execution:** enter at the next day's open; hold to the open after the next decision.

**XR, cross-sectional short-term reversal** (weekly):
- **Decision:** at the last trading day of each week.
- **Ranking:** by the past 5-day return.
- **Positions:** long the bottom 20% (losers), short the top 20% (winners); vol-scaled, half the risk each side.
- **Execution:** next open to next open.

**ON, NIFTY overnight:**
- **Rule:** long NIFTY from each close to the next open.
- **Return:** open / previous close − 1, minus 2 × 4 bp.

**Portfolio return:**
- **XM / XR:** per period, the weighted sum of the open-to-open returns. Gross exposure is normalised to 1 (long 0.5 + short 0.5 of capital); costs on turnover as in tsmom.

**Pass (each; Bonferroni over 3, so p < 0.0167):** all four of
1. mean net return per period > 0;
2. a block bootstrap 95% CI above 0 (blocks of 4 periods for XR, 3 for XM, 20 days for ON);
3. a one-sided t-test p < 0.0167;
4. annualised net Sharpe ≥ 0.5.

**Stages:**

| Stage | Period |
|---|---|
| Train | 2019-01-01 → 2024-12-31 |
| Validation | 2025 (only passes) |
| Final, one shot | 2026-01-01 → 2026-10-21 (only after a validation pass) |

**Reported:**
- every number, the 12 bp stress, the long and short legs separately;
- the correlation of the weekly/monthly returns with NIFTY, to check the neutrality.

**Use:**
- **A config that passes all three stages:** becomes a paper book (weekly/monthly positions at live quotes) and is reported to the owner.
- **Never a reason to trade real money by itself.**
