# Cross-sectional momentum, short-term reversal, NIFTY overnight: result (25 Oct 2026, evening)

**Protocol:** `xs_protocol.md`, SHA-256 `79239261730c9b0650fba417d363b548973e1c0879aa59727731012e3db5d5f2`, registered at 17:45 before any result.
**Code:** `nfce_engine/tools/xs.py`. It reuses the loader, the calendar and the roll logic of `tsmom.py`. It was checked first on synthetic data:
- random walk: both about 0;
- persistent drifts: XM +3.2% a month, XR negative;
- planted reversal: XR +0.87% a week, XM about 0.

**Data:** Upstox daily, 213 F&O stocks, 2016–26. **Costs:** 8 bp per side on turnover plus the roll; NIFTY 4 bp per side.

## Train 2019–24 (Bonferroni, p < 0.0167 needed)
| Rule | Periods | Net per period | Gross | Sharpe | p | 95% CI | Max DD | Total | Long / short legs | Corr with NIFTY | Verdict |
|---|---|---|---|---|---|---|---|---|---|---|---|
| XM (12-1 momentum, monthly, market-neutral) | 70 months | **+0.515%** | +0.719% | +0.63 | 0.066 | −0.163..+1.124% | 15.7% | +39.4% | +1.691 / −0.972 | −0.18 | FAIL (p) |
| XM at 12 bp | | +0.413% | | +0.51 | 0.112 | | 16.7% | +29.8% | | | |
| XR (5-day reversal, weekly, market-neutral) | 308 weeks | −0.023% | +0.155% | −0.17 | 0.656 | −0.138..+0.097% | 19.4% | −8.1% | +0.347 / −0.192 | +0.15 | FAIL |
| **ON (NIFTY close → next open, long)** | 1,488 days | **+0.051%** | +0.131% | **+1.15** | **0.0025** | **+0.012..+0.087%** | 27.9% | +106.6% | long only | (it is the index) | **PASS** |

## Validation 2025, ON only (249 days, one look): FAIL
| | Net per day | Gross | Sharpe | p | 95% CI | Max DD | Total |
|---|---|---|---|---|---|---|---|
| ON | **−0.044%** | +0.036% | −1.33 | 0.908 | −0.074..−0.011% | 11.5% | **−10.6%** |
| NIFTY in 2025 (for reference) | | | | | | | +10.5% |

The 2026 final is not run.

## What it means
1. **ON:** the overnight effect was strong in 2019–24 (+0.131% a day gross) but nearly vanished in 2025 (+0.036%). At 8 bp of cost every day, it lost 10.6% in a year when NIFTY rose 10.5%. Like TS250, a long-only rule that passed a bull-market training period and failed the next year. Not adopted.
2. **XM, market-neutral momentum, was the closest so far:**
   - positive after costs (+0.52% a month, Sharpe 0.63), with a slightly negative correlation to NIFTY, so not bull-market beta;
   - the long leg made the money; the short leg lost about half of it back;
   - 70 months were not enough to pass the strict bar (p 0.066 against 0.0167). **It FAILS here and is not used.**
   - **A fair next test:** an independent, older sample. Upstox serves another 10 years per request, so 2006–2016 would be data never used. It must be registered before looking, with this exact rule unchanged.
3. **XR:** the reversal premium before costs (+0.155% a week) is eaten by its weekly turnover (1.60): not viable at these costs.

**Correction (25 Oct, later):** a data-handling bug (the calendar included special NIFTY sessions without stock candles, which dropped stocks for about 3 months after each) was found in the 2006–16 run. It was fixed in `tsmom.load`, and this test was re-run: **the verdicts are unchanged** and the numbers shift slightly. See `xm_old_result.md` for the old and new numbers.
