# Time-series momentum on F&O stock futures, weekly: result (22 Oct 2026, evening)

**Protocol:** `tsmom_protocol.md`, SHA-256 `030dfa7ccb432bc49381a4a9301eb1b23f3f2ca595c049c21dacdb23b36de0c2`, registered at 19:19 before any result.
**Code:** `nfce_engine/tools/tsmom.py`. Checked first on synthetic data:
- random walks gave about 0 gross (+0.019% a week) and a loss net of costs (no look-ahead);
- persistent ±trends earned on both sides.

One bug was found by the synthetic check (week labels misaligned, so no trades) and fixed before any real run.

**Data:** Upstox daily, 213 F&O stocks, 2016-10 → 2026-10.
**Costs:** 8 bp per side (measured: fees 3.2 bp, half-spread 4.4 bp on 22 Oct), plus the monthly roll; stress 12 bp.

## Train 2019–24 (313 weeks)
| Config | Net %/week | Gross | Sharpe | p | 95% CI (block) | Max DD | Long part | Short part | Verdict |
|---|---|---|---|---|---|---|---|---|---|
| TS60 | +0.069 | +0.106 | +0.72 | 0.040 | −0.007..+0.152 | 9.9% | +0.176 | −0.070 | FAIL |
| TS120 | +0.077 | +0.111 | +0.79 | 0.027 | −0.001..+0.163 | 12.0% | +0.178 | −0.067 | FAIL |
| **TS250** | **+0.120** | +0.151 | **+1.18** | **0.002** | **+0.041..+0.202** | 6.7% | +0.198 | −0.047 | **PASS** |
| TS250 at 12 bp | +0.104 | | +1.03 | 0.006 | +0.025..+0.186 | 7.7% | | | |
| Bench: equal-risk long-only | +0.220 | | +1.27 | 0.001 | | 18.6% | | | |
| Bench: NIFTY buy & hold | +0.287 | | +0.84 | 0.020 | | 36.1% | | | |

## Validation 2025, TS250 only (52 weeks, one look): FAIL
| | Net %/week | Sharpe | p | 95% CI | Max DD | Total | Long part | Short part |
|---|---|---|---|---|---|---|---|---|
| **TS250** | **−0.101** | **−1.66** | 0.948 | −0.272..+0.023 | 4.2% | **−5.2%** | +0.031 | −0.098 |
| TS250 at 12 bp | −0.118 | −1.95 | | | | −6.0% | | |
| Bench: equal-risk long-only | +0.101 | +0.49 | | | | +4.8% | | |
| Bench: NIFTY buy & hold | +0.197 | +0.67 | | | | +9.5% | | |

The 2026 final stage is not run.

## What it means
1. **The train pass was the bull market showing through.**
   - In 2019–24 the long half made all the money; the short half lost, even then.
   - Being long the same stocks beat it outright (Sharpe 1.27 vs 1.18).
   - In 2025 the trend signals were whipsawed (40% up-weeks), and the shorts lost again.
2. **Momentum as a stand-alone edge in these stocks is not shown;** its one real merit on train was a lower drawdown (6.7% vs 18.6%).
3. **Survivorship bias** (today's F&O list) flattered the long side, and it still failed.
4. **Nothing goes live.**

**Correction (25 Oct, later):** a data-handling bug (the calendar included special NIFTY sessions without stock candles, which dropped stocks for about 3 months after each) was found in the 2006–16 run. It was fixed in `tsmom.load`, and this test was re-run: **the verdicts are unchanged** and the numbers shift slightly. See `xm_old_result.md` for the old and new numbers.
