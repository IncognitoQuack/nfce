# XM on the untouched 2006–2016 sample: result (25 Oct 2026, evening)

**Protocol:** `xm_old_protocol.md`, SHA-256 `6cf083967bd4f1e801e298708ae272654cc7becda400bf5109d7cd0451868bb7`, registered at 17:49 before this data was downloaded.
**Data:** Upstox daily, 2006-10-23 → 2016-10-21, for 158 of today's F&O stocks plus NIFTY. The other 55 had not listed yet (HAL, LIC, Zomato, …), as expected. 19 corporate-action gaps were neutralised by the rule.
**Rule:** XM exactly as registered (`tools/xs.py` unchanged): monthly 12-1 momentum, long the top 20% / short the bottom 20%, equal risk; 8 bp per side plus the roll.

## A bug found during this run (data handling; fixed, then everything affected was re-run)
1. **Duplicate rows:** the 2006–16 files repeat 2015-12-31 once, with identical rows. The loader now drops exact duplicate dates.
2. **The calendar bug:** the calendar came from NIFTY's trading days, which include special sessions (Muhurat / Saturday) with no stock candles.
   - After each one, most stocks' 60-day volatility became undefined for about 3 months, and they silently dropped out.
   - On 2006–16 that skipped 31 of 107 months. The first run gave **−0.478%/month on 76 months**; that number is **invalid**.
   - The loader now keeps only days on which at least half of the listed stocks traded.
   - It also affected the 2016–26 data (Muhurat 2016/2017/2018), so the 25 Oct tests were re-run (below).

## Result with the fix (106 of 107 months; median 137 stocks ranked per month; 0 skipped)
| | Net per month | Gross | Sharpe | p | 95% CI | Max DD | Total | Long / short legs | Corr with NIFTY |
|---|---|---|---|---|---|---|---|---|---|
| **XM 2007-11 → 2016-09** | **−0.201%** | **+0.003%** | −0.18 | 0.700 | −1.228..+0.695% | 41.2% | −25.9% | +0.926 / −0.923 | −0.48 |
| XM at 12 bp | −0.303% | | −0.27 | 0.785 | | 42.2% | −33.6% | | |

**FAIL.** Before costs, momentum earned essentially nothing in this decade: the long and short legs cancelled out. The 41% drawdown matches the momentum crashes known from the 2009 rebound. **XM is closed.**

## The 25 Oct tests re-run with the calendar fix: every verdict unchanged
| Test | Reported 25 Oct | With the fix |
|---|---|---|
| XM 2019–24 | +0.515%/mo, p 0.066, FAIL | +0.524%/mo, p 0.059, FAIL |
| XR 2019–24 | −0.023%/wk, FAIL | −0.027%/wk, FAIL |
| ON 2019–24 / 2025 | PASS / −10.6%, FAIL | identical |
| TS60 / TS120 train | FAIL / FAIL | FAIL / FAIL (TS120 p 0.021 > 0.0167) |
| TS250 train / 2025 | Sharpe 1.18 PASS / −5.2%, FAIL | Sharpe 1.10 PASS / −5.2%, FAIL |
