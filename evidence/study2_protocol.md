# Study engine v2: literature-specified intraday hypotheses with measured costs (registered 26 Oct 2026, before any run)

**Why a v2:** the owner asked for a deeper, bank-grade study after v1 (`study_engine_result.md`: 2,232 rules, 0 survivors). They also asked to fix v1's mistakes ("volume to volatility" and others), to use the published research and the news, and to test again.

**What v2 does differently:** it does **not** mine a large grid. It tests **8 hypotheses whose rules come from published research or from v1's single lead**, with the published parameters, so the multiple-testing burden is small and honest. It also uses **costs measured from the order book**.

**Code:** `nfce_engine/tools/study2.py`; tests `nfce_engine/tests/test_study2.py` (synthetic only).

## v1 mistakes this fixes
| v1 mistake | v2 fix |
|---|---|
| Fixed % thresholds (e.g. a 2% gap) ignore each stock's own volatility | Thresholds and stops in ATR units (H2, H3, H8) |
| Relative volume used as a direction signal on every stock | Relative opening volume (vs the same window over 14 days) **selects** the 20 "stocks in play" across the market each day (H1, H2), as in the literature |
| Every stock traded every day, pooled | Cross-sectional selection: top 20 in play (H1/H2); 10 long / 10 short (H6) |
| Symmetric 1:1 stop/target only | The literature's asymmetric exit: a stop, no target, hold to the close (H1–H3) |
| Friction 2 bp per side, futures only | **Order-book-measured impact**: cash-equity intraday ₹3 L at **3.7 bp per side (5.0 bp in the first 15 minutes)**; stock futures at 4.9 / 6.3 bp as a cross-check |
| The cheaper venue was ignored | Since 1 Apr 2026, futures STT is 0.05% (Budget 2026) while cash-equity intraday STT stays 0.025%. **Primary venue for stocks = cash-equity intraday (MIS)**, fixed now from the 22–23 Oct order books, before any result |
| No time-of-day effects | Last-half-hour tests: H4, H5 (index), H6 (stocks) |
| No news | Dated news: results (board-meeting) days, H3. Live LLM news can only be tested forward (below) |
| Index friction 4 ticks | Measured NIFTY half-spread ≈ 2.6 pts ≈ **1 bp of price per side** (both indices); 4 ticks shown as a sensitivity |

**Already tested, not repeated:** the noise-area momentum (Zarattini, Aziz and Barbon 2024) failed in `external_result.md` (S2, −0.156R).

## Data
- **Stocks:** `hist3m_fo` (213 F&O stocks, 3-minute bars).
- **Index:** `hist5m_index` (NIFTY, BANKNIFTY, 5-minute bars).
- **VIX:** INDIA VIX 3m.
- **Results calendar:** `nfce_data/results_calendar.csv` (NSE board meetings with results = 1).
- Sessions with fewer than half the normal bars are dropped.
- **No look-ahead:** signals use bars ≤ t; fills happen at the next bar's open, or at the stop level inside a later bar; daily values use earlier days only.

## The 8 hypotheses (rules fixed here; the parameters come from the sources)
| Hyp | Rule | Source |
|---|---|---|
| **H1** | **Stocks-in-play ORB.** Opening range = the first two 3m bars (09:15–09:21, the closest to 5 minutes). Eligible: relative OR volume ≥ 1 (vs the mean of the same window over the previous 14 sessions), daily ATR14 ≥ 1% of price, OR candle not flat. **Top 20 by relative volume**, chosen at 09:21 from all eligible stocks. Direction = the OR candle (up → long only, down → short only). Entry: a stop order at the OR high (low), from 09:21 to bars starting by 15:00; filled at the level, or at the bar's open if it gaps through. **Stop 0.10 × ATR14**, no target, exit at the bar closing 15:15 | Zarattini, Barbon and Aziz (2024), "A Profitable Day Trading Strategy for the U.S. Equity Market" |
| **H2** | H1 with a **stop of 0.50 × ATR14** (the cost-aware version: a 0.10 ATR stop is about 0.3% of price, against about 0.13% round-trip costs) | H1 |
| **H3** | H2's rule on **results days** (the board-meeting session and the one after), every eligible stock (no top-20 cut) | news / earnings-day "in play"; post-announcement drift |
| **H4** | **Index intraday momentum:** sign of (09:45 close / prior close − 1) → trade NIFTY and BANKNIFTY futures from the 15:00 open to the 15:30 close | Gao, Han, Li and Zhou (2018) |
| **H5** | Sign of (15:00 / prior close − 1) → the same 15:00 → 15:30 trade | Baltussen, Da, Lammers and Martens (2021), hedging-demand market intraday momentum |
| **H6** | **Stock end-of-day reversal:** at 14:57 rank stocks by return since the prior close; **buy the 10 worst, sell the 10 best**; 14:57 open → 15:18 close (before the brokers' MIS square-off) | stock-level end-of-day reversal (opposite of market momentum) |
| **H7** | **v1's only lead, exactly:** `GAP_FADE|L|K2|ALL|VIXLO|STK|0.02` (a ≥ 2% gap down, low VIX, long after the first bar, stop and target 0.5 × ATR) | `study_engine_result.md`; its 2022–24 numbers were mined, so **only its final counts** |
| **H8** | **Gap fade in ATR units:** a gap ≥ 1.0 × ATR14 down → long, up → short, after the first bar; stop and target 0.5 × ATR14 (v1 K2), both sides pooled | H7 corrected for volatility |

**R** (the unit of results) = the stop distance (H1: 0.10 ATR; H2, H3: 0.50 ATR; H7, H8: 0.50 ATR). For H4–H6, which have no stop, R = 0.25 × ATR14. Net basis points per trade are reported for all eight.

## Costs (fixed now, before any result)
- **Stocks, primary venue: cash-equity intraday, ₹3 L per trade.**
  - **Fees:** STT 0.025% on the sell side; NSE 0.00322% each side; SEBI ₹10/crore; stamp 0.003% on the buy side; brokerage min(₹20, 0.03%) per order; GST 18%.
  - **Impact per side** (median depth-walked cost of a ₹3 L market order, 213 stocks, 22–23 Oct): **3.7 bp**; **5.0 bp** for an entry bar starting before 09:30.
- **Stocks, cross-check venue:** one stock-futures lot of about ₹7 L at the current fee schedule plus 4.9 bp per side (6.3 bp at the open).
- **Index:** futures at one lot, current fees, plus **1 bp of price per side**. The old 4 ticks are shown as a sensitivity.
- **Short selling** in cash intraday is allowed (MIS). Borrowing is not needed intraday.

## Stages
| Stage | Dates | Runs | Gate |
|---|---|---|---|
| **Development** | 2022-01-01 .. 2024-12-31 | all 8 | net R per trade > 0 after costs |
| **Final** | 2025-01-01 .. 2026-10-21 | only the hypotheses that passed the gate; **once** (`--i-accept-one-shot`; the tool refuses a second run) | below |

- The tool refuses the final if this file's hash changed since development.
- Development is only a gate:
  - 2022–24 were seen by earlier studies (other rules);
  - H7 was found on 2022–24.
- **The final years 2025–26 have not been used by any indicator-rule test** (v1 stopped at validation).

## Pass rule (final, each hypothesis)
All four:
1. at least 100 trades;
2. net R per trade > 0 after the primary costs;
3. **Holm-adjusted** one-sided p(day), on the day means, < 0.05, with the family = **all 8 hypotheses** (those not run count as p = 1);
4. the 95% day-block bootstrap interval of net R per trade is above 0.

**Also reported:**
- Hansen's SPA and White's reality check over the final hypotheses;
- per-year numbers;
- long and short separately;
- the cross-check venue and the 4-tick index sensitivity.

**A pass needs the primary costs.** The cross-check venue is information only.

## What a pass would mean
- A hypothesis that passes gets a **locked live paper protocol** (a separate strategy account, judged after a fixed number of sessions).
- **Nothing goes straight to real money.**
- The paper test also measures the real fills, which no backtest can.

## What a fail would mean
- The published intraday effects do not survive realistic Indian costs on these instruments in 2025–26, and the next lever is not another indicator.
- The plan in the result says what is left:
  - cheaper execution;
  - option structures on the range model's proven skill;
  - forward news tests.

## News and LLMs
- **Not backtestable:** there is no point-in-time archive here, and an LLM knows the outcomes of past headlines.
- **H3 uses the only dated news in the data:** results days.
- **A forward test** (the LLM reads the headline, the verdict is logged before the move, and it is judged after N sessions) is proposed in the result, not run.
