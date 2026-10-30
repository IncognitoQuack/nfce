# Study engine: many intraday indicator rules at once (registered 26 Oct 2026, before any run)

**Why:** 16 locked tests found nothing that passes every stage. The owner asked for one engine that tests all the common intraday tricks and indicators on all of the stored history, with realistic costs and protection against data-mining luck.
**The danger:** testing hundreds of rules guarantees that some look good by chance. This protocol fixes, before any data is looked at, how a rule must win to count.

**Code:** `nfce_engine/tools/study.py`; tests `nfce_engine/tests/test_study.py` (synthetic data only). Run with `nice -n 15`, at most 6 worker processes, while the live bridge runs.

## Data
- **Stocks:** `~/Downloads/nfce_data/hist3m_fo/`: 3-minute candles of the 213 F&O stocks with history, 2022-01 to 2026-10.
- **Index:** `hist5m_index/` NIFTY and BANKNIFTY, 5-minute (no volume, so the volume rules are not run on them).
- **VIX:** `hist3m_fo/INDIAVIX_3m.pkl`, for the regime filter only.
- Regular-session bars only (09:15 to 15:30). Days with fewer than half the normal bars (special sessions, broken days) are dropped.
- **The live minute quotes** (`nfce_bridge/data/study_quotes_20261022.db`, `…23.db`) are used **only** to check the cost model's spread assumption. They are never used to choose or judge a rule.

## No look-ahead
- An indicator's value at bar t uses bars up to and including t.
- Daily values (prior-day high/low/close, ATR, NR7, inside day, VIX regime) use earlier days only.
- **Entry:** the open of the bar after the signal bar, on the same day.
- **Trades:** at most one per rule, instrument and day: the day's first signal inside the time window. The trade cannot be re-entered.

## The rule grid (every rule is run; nothing is added after the run)
**One rule** = indicator × setting × side × exit × time window × VIX regime × universe.

### Indicators and settings (16 indicators, 37 settings)
| Indicator | Long signal (short is the mirror image) | Settings |
|---|---|---|
| RSI_MR (mean reversion) | RSI(n) crosses up through lo (short: down through 100 − lo) | (14, 30), (14, 25), (7, 20) |
| RSI_TR (trend) | RSI(n) crosses up through hi (short: down through 100 − hi) | (14, 60), (14, 70), (7, 70) |
| MACD | MACD crosses above its signal line | (12, 26, 9), (6, 13, 5) |
| BB_BRK | close crosses above the upper Bollinger band (n, k) | (20, 2.0), (20, 2.5) |
| BB_FADE | close crosses back above the lower band (short: back below the upper) | (20, 2.0), (20, 2.5) |
| ST | Supertrend (ATR n, multiplier m) flips up | (10, 3), (10, 2) |
| VWAP_X | close crosses above session VWAP × (1 + b) (not on the day's first bar) | b = 0, 0.2% |
| VWAP_MR | close falls below VWAP × (1 − k): buy the stretch | k = 0.75%, 1.5% |
| ORB | first close above the opening-range high (first 15/30 minutes) | 15, 30 |
| EMA_X | EMA fast crosses above EMA slow | (9, 21), (5, 13), (20, 50) |
| ADX_DI | +DI crosses above −DI while ADX(14) > th | th = 20, 25 |
| RVOL | bar volume ≥ k × the same time slot's mean over the previous 10 days, and the bar closes up | k = 3, 5 |
| GAP_CONT | the day opens ≥ g above the prior close: buy after the first bar | g = 0.5%, 1%, 2% |
| GAP_FADE | the day opens ≥ g below the prior close: buy after the first bar | g = 0.5%, 1%, 2% |
| PDHL | close crosses above the prior day's high × (1 + b) | b = 0, 0.25% |
| NR_ORB | ORB-15 on a day after an NR7 day, or after an inside day | nr7, inside |

**Other dimensions:**
- **Side:** long, short.
- **Exits** (as in `wide_stop.py`): R = 0.25 × the prior days' daily ATR14. Stop and target both at k × R, all out, square-off on the bar closing 15:15. k = **1 (K1), 2 (K2), 4 (K4)**.
  - Same walk as `research2._walk`: the stop is checked first when both are touched in one bar; a gap through the stop fills at the open.
  - Results are in units of the risk taken: net R = net points / (k × R).
- **Time window:** the signal bar must close by **14:30 (ALL)** or by **11:00 (AM)**. The gap rules fire at the open only, so they have one window.
- **VIX regime:** ALL days; **VIXHI**, the previous VIX close above the median of the 20 closes before it; **VIXLO**, otherwise.
- **Universe:** STK (each rule run on all 213 stocks, pooled) and IDX (NIFTY and BANKNIFTY futures, pooled; no RVOL/VWAP rules).

**Size:** 2,232 rules (1,224 STK, 1,008 IDX). **N = 2,232** is the number of trials used in every multiple-testing correction below.

## Costs (the house model; nothing new)
- **Stock futures:** `costs.futures_cost_points` at the current (2026) fee schedule, one lot of about ₹7 L notional, 2 orders, plus friction of **0.02% of price per side** (as `stock3m_research.py`).
- **Index futures:** one lot (NIFTY 65, BANKNIFTY 30), plus **4 ticks per side** (as `research_run.py`).
- The current schedule is applied to every year (the stricter choice).

## Stages
| Stage | Dates | What runs | What is decided |
|---|---|---|---|
| **Train** | 2022-01-01 .. 2023-12-31 | all 2,232 rules | **Choosing the settings:** per family (all dimensions except the setting), the setting with the best net R per trade among those with ≥ 100 trades. That setting is a **candidate** only if its train net R > 0 |
| **Validation** | 2024-01-01 .. 2024-12-31 | the candidates only | survivors (pass rule below) |
| **Final** | 2025-01-01 .. 2026-10-21 | the validation survivors only, **once** (`--i-accept-one-shot`; the tool refuses a second run) | the verdict |

The tool refuses validation or final if this file's hash differs from the one recorded at train.

## Statistics
- **Per rule:** n, win %, gross and net R per trade, R per trade per year, exits, and the cost share of the risk.
- **p(day):** a one-sided t-test on the day means of net R per trade (house standard: trades on one day are not independent).
- **Daily series** for the data-snooping tests: the day mean of net R per trade, and 0 on days with no trade (one unit of risk a day).
- **White's reality check and Hansen's SPA** (consistent version, studentised):
  - stationary bootstrap, mean block 5 days, 1,000 resamples;
  - H0: no rule beats not trading;
  - run on train over all rules with trades, and on validation over the candidates.
- **Deflated Sharpe ratio** (Bailey and López de Prado): per-day Sharpe against the expected best of **N = 2,232** skill-less trials, with V[SR] taken from the spread of the train Sharpes across rules.
- **Holm-adjusted p-values**, with the family = **all 2,232 rules tried**. Rules that were not validated count as p = 1. The Holm values with only the candidates as the family are also reported, as information.

## Pass rule (a rule "survives" only if ALL hold)
1. **Validation 2024:**
   - at least 30 trades;
   - net R per trade > 0 after costs;
   - Holm-adjusted p(day) over all 2,232 rules < 0.05;
   - deflated Sharpe ratio ≥ 0.95.
2. **Final 2025–26 (one shot):**
   - net R per trade > 0 after costs;
   - one-sided p(day) < 0.05 / (the number of rules in the final).

The 95% day-block interval and the DSR are reported in the final too.

## Report
- `evidence/study_engine_result.md`:
  - the scale (rules, trades);
  - the top train rules;
  - the candidates' validation table;
  - the final table, if any;
  - the SPA / reality check / DSR / Holm verdicts;
  - the cost-model check;
  - a plain bottom line.
- `evidence/study_engine_rules.csv`: every rule's numbers (train for all; validation and final only where they were run).

## What a pass would and would not mean
- **A survivor** gets a **proposed** locked protocol for a live paper test. Nothing is switched on live from this study.
- **No survivor** means that none of these common indicator rules beats futures costs reliably on these stocks and indices. **This is the expected result**, given that the system's own signals had a gross edge of about +0.05R against costs of about 0.3R.

## Disclosed in advance
- **Prior years were seen before.** 2022–2025 were already used by earlier tests of the NFCE signals (different entries). The indicator rules here have not been run on any year before.
- **News and LLMs are not in this study.** There is no archive of news as it was known at each bar. An LLM reading old headlines also knows what happened next, so a backtest would be contaminated. It can only be tested forward, under its own locked protocol.
