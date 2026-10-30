# Study engine v2: result (26 Oct 2026)

**Protocol:** `study2_protocol.md`, SHA-256 `98291e82aacfc8325b4203635aa4a2a0ac2f8b3d3c3a6a2d4a84e67208e872bc`, registered at 10:57 IST before any run (REGISTRY row added then).
**Code:** `nfce_engine/tools/study2.py`, with 12 tests in `nfce_engine/tests/test_study2.py`:
- equity fees by hand;
- the order-book walk;
- ORB entry and stop;
- the top-20 chosen at 09:21 from all eligible stocks (a look-ahead bug in the first draft was caught by this test before any run);
- results days;
- the end-of-day ranking;
- the index sign;
- gaps in ATR.

**Runs:**
- development 2022–24, all 8 hypotheses (3 s);
- the one-shot final 2025-01 .. 2026-10-21, for H7 only (the only one past the gate).

**Summary file:** `study2_trades_summary.csv`.

## Bottom line
- **0 of 8 literature-based hypotheses pass.** One (H7) reached the final and failed it.
- **What the deeper study found that v1 could not:**
  1. **The cost model was wrong, and the cheaper venue was ignored.**
     - The order books show stock futures cost about 4.6–4.9 bp per side, not 2.
     - Cash-equity intraday costs about 3.7 bp per side at ₹3 L, and its STT is half (0.025% vs 0.05% on futures since 1 Apr 2026).
     - A realistic round trip is **≈ 12.6 bp in cash equity**, against ≈ 16 bp in futures. v1 had assumed ≈ 10.5 bp.
  2. **"Stocks in play" have a real gross edge.**
     - The published opening-range breakout on the 20 stocks with the highest relative opening volume makes **+10 to +13 bp per trade before costs**.
     - It is consistent in 2022, 2023 and 2024.
     - That is the size of the cost of a market order, so **net it is about zero** (−2.6 to +2 bp, depending on the stop and on how the breakout bar is modelled).
     - **This is the first idea in 18 tests whose gross edge equals its costs.** It is a question of execution, not of a better indicator.
  3. **The "fade the gap-down" lead from v1 is real, but it is a rare-event effect, not a daily rule.**
     - In the final years it made **+0.121R per trade (+22 bp after costs), positive in both 2025 and 2026**.
     - Its average *day* lost, though (p(day) 0.98): almost all of the profit came from a few market-wide panic gap-downs (2025-06-13, 2026-04-13).
     - Without its 5 best days it loses −0.15R per trade. It fails the locked rule.
  4. **The famous time-of-day effects do not work here.**
     - Index last-half-hour momentum (two versions) has gross ≈ 0 against 8 bp of cost.
     - Stock end-of-day reversal is negative even before costs.
- **Nothing is switched on.** The plan at the end says how the engine can be used to look for profit without fooling ourselves.

## Sources used (web research, 26 Oct)
- Zarattini, Barbon, Aziz (2024), *A Profitable Day Trading Strategy for the U.S. Equity Market* (5-minute ORB on stocks in play: top 20 by relative opening volume, stop 10% of ATR, hold to the close). Rules via [CXO Advisory](https://www.cxoadvisory.com/individual-investing/intraday-trading-of-overactive-stocks-via-opening-range-breakout/) and the [QuantConnect replication](https://www.quantconnect.com/research/18444/opening-range-breakout-for-stocks-in-play/). Its replication comments warn that costs eat much of the return, and that some years fail.
- Gao, Han, Li, Zhou (2018), *Market intraday momentum* ([summary](https://alphaarchitect.com/2014/08/attention-prop-traders-the-first-half-hour-of-trading-predicts-the-last-half-hour/)). No NSE replication was found.
- Baltussen, Da, Lammers, Martens (2021), hedging-driven market intraday momentum. At the stock level the pattern reverses (as summarised from the [Notre Dame paper](https://www3.nd.edu/~zda/EOD.pdf); its PDF could not be read here).
- Zarattini, Aziz, Barbon (2024), *Beat the Market* (noise area). [SFI listing](https://www.sfi.ch/de/publications/n-24-97-beat-the-market-an-effective-intraday-momentum-strategy-for-s-p500-etf-spy). Already failed here (`external_result.md`), so it was not repeated.
- Heston, Korajczyk, Sadka (2010), intraday periodicity ([paper](https://ar5iv.arxiv.org/html/1005.3535)). Not tested: the authors size the effect at about the effective spread, so it cannot pay a 12.6 bp round trip.
- Lopez-Lira and Tang, *Can ChatGPT forecast stock price movements?* ([arXiv](https://arxiv.org/abs/2304.07619v5)). LLM news scores predict next-day drift, mostly in small stocks and after bad news; the returns fall as LLM use spreads.
- **News that changes the costs:**
  - Budget 2026 raised futures STT to 0.05% and option STT to 0.15% from 1 Apr 2026, while cash-equity intraday stays at 0.025% ([Outlook Money](https://www.outlookmoney.com/invest/stt-hike-from-april-1-2026-budget-what-it-means-for-futures-and-options-traders), [Zerodha STT](https://support.zerodha.com/category/account-opening/resident-individual/ri-charges/articles/how-is-the-securities-transaction-tax-stt-calculated)).
  - Zerodha's NSE equity transaction charge is listed as 0.00297–0.00322% on different pages, so the higher figure is used.
- **Context:** SEBI found 91% of individual F&O traders lost money in FY25 (₹1.05 lakh crore), and only 0.5% were profitable in all of FY22–26 ([Moneylife](https://moneylife.in/article/91-percentage-of-retail-traders-lost-money-in-derivatives-losses-in-fo-surged-41-percentage-to-rs105-lakh-crore-in-fy25-sebi-study/77613.html)).

## Development 2022-01 .. 2024-12 (gate: net R > 0 after the primary costs)
| Hyp | What | n | Win % | Gross R | **Net R** | Net bp | Cost bp | Long / short net R | 95% day-block | p(day) | Alt cost net R¹ | Gate |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H1 | Stocks-in-play ORB, paper stop 0.10 ATR | 11,296 | 8.4 | −0.370 | **−0.817** | −23.8 | 12.6 | −0.880 / −0.747 | −0.869..−0.767 | 1.000 | −0.944 | FAIL |
| H2 | Stocks-in-play ORB, stop 0.50 ATR | 11,296 | 42.7 | +0.071 | **−0.018** | −2.6 | 12.6 | −0.038 / +0.004 | −0.047..+0.009 | 0.878 | −0.044 | FAIL |
| H3 | ORB on results days (dated news) | 2,599 | 42.7 | +0.086 | **−0.005** | +0.9 | 12.6 | −0.089 / +0.054 | −0.060..+0.048 | 0.668 | −0.031 | FAIL |
| H4 | Index: first half hour → last half hour | 1,448 | 32.9 | −0.000 | **−0.273** | −8.1 | 8.0 | −0.242 / −0.312 | −0.320..−0.224 | 1.000 | −0.218 | FAIL |
| H5 | Index: rest of day → last half hour | 1,448 | 33.7 | +0.016 | **−0.257** | −7.5 | 8.0 | −0.224 / −0.297 | −0.302..−0.210 | 1.000 | −0.202 | FAIL |
| H6 | Stocks: end-of-day reversal 10/10 | 14,480 | 33.0 | −0.047 | **−0.200** | −17.2 | 12.6 | −0.144 / −0.257 | −0.215..−0.185 | 1.000 | – | FAIL |
| H7 | v1 lead: fade a ≥ 2% gap down, low VIX | 1,162 | 54.2 | +0.166 | **+0.083** | +16.0 | 13.9 | +0.083 / – | −0.093..+0.255 | 0.220 | +0.061 | pass |
| H8 | Fade a gap ≥ 1 ATR, both sides | 1,750 | 47.8 | −0.005 | **−0.107** | −14.9 | 13.9 | −0.098 / −0.116 | −0.217..+0.008 | 0.999 | −0.134 | FAIL |

¹ "Alt cost" is the stock-futures venue for the stock rules, and the old 4-tick friction for the index rules.

**Net R per trade by year (trades):**

| Hyp | 2022 | 2023 | 2024 |
|---|---|---|---|
| H1 | −0.700 (3,719) | −0.924 (3,778) | −0.825 (3,799) |
| H2 | −0.021 (3,719) | −0.033 (3,778) | −0.001 (3,799) |
| H3 | +0.034 (864) | −0.079 (833) | +0.026 (902) |
| H4 | −0.203 (466) | −0.333 (490) | −0.278 (492) |
| H5 | −0.147 (466) | −0.304 (490) | −0.314 (492) |
| H6 | −0.182 (4,660) | −0.233 (4,900) | −0.185 (4,920) |
| H7 | +0.085 (511) | −0.005 (222) | +0.127 (429) |
| H8 | −0.082 (551) | −0.067 (516) | −0.157 (683) |

## Final 2025-01 .. 2026-10-21 (one shot, H7 only)
| Hyp | n | Days | Win % | Gross R | **Net R** | Net bp | 2025 | 2026 | 95% day-block | p(day) | Holm (8) | Pass |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| H7 | 671 | 148 | 59.2 | +0.208 | **+0.121** | +22.2 | +0.150 (309) | +0.095 (362) | −0.145..+0.306 | 0.982 | 1.000 | **FAIL** |

SPA over the final: p = 1.000; reality check p = 0.962.

**PBO (CSCV, 16 blocks; added 26 Oct, 11:45):**
- Over the 8 hypotheses on development: **0.00**. The development-best (H7) has a per-day Sharpe of +0.030 in sample and **+0.004 out of sample**.
- It ranks above the other seven only because they lose. Its own out-of-sample Sharpe is about zero, as the final then confirmed.
- PBO measures selection relative to the other trials, not profit against zero.

**Why a +0.121R rule fails:**

| Sample | Positive days | Top 5 days' share of total R | Net R per trade without the top 5 days |
|---|---|---|---|
| Dev | 49% | 166% | −0.072 |
| Final | 41% | 181% | −0.153 |

- The profit is a few market-wide panic opens with 73–136 gap-down stocks at once: 2022-08-29, 2024-12-19, 2025-06-13, 2026-04-13. Buying all of them caught the rebound.
- **That is one bet repeated on a handful of days**, not 671 independent trades. The day-level test is right to reject it.

## Checks that change how the numbers should be read (descriptive; not part of the pass rule)
1. **The breakout bar (H1–H3).**
   - With 3-minute bars it is unknowable whether a breakout bar's low came before or after the breakout.
   - The registered run assumes the worst: a touch of the stop in that bar counts as a stop-out.
   - Assuming the best instead (2022–24):

| Hyp | Gross R | Net R | Net bp | Win % |
|---|---|---|---|---|
| H1 | +0.434 | −0.013 | +0.2 | 17.4 |
| H2 | +0.080 | −0.010 | −1.3 | 43.0 |
| H3 | +0.094 | +0.003 | +2.1 | 43.1 |

   - **The truth lies between the two runs, and neither is a profit after market-order costs.**
   - 1-minute history would narrow it; the live recorder now collects it.
2. **Order-book cost check** (`study2.py costcheck`; 35,682 sampled quotes, 22–23 Oct):

| Per side, vs mid | ₹1 L | ₹3 L | ₹7 L | First 15 min (₹3 L) |
|---|---|---|---|---|
| Cash equity, buy | 2.7 bp | 3.7 bp | 5.4 bp | 4.7 bp |
| Cash equity, sell | 2.9 bp | 3.9 bp | 5.5 bp | – |
| Stock futures, buy | 4.6 bp | 4.6 bp | 4.9 bp | 6.1 bp |
| NIFTY futures, half-spread | 1.2 bp (≈ 3 pts) | | | |

   - Cash equity is cheaper per side than futures at ₹1–3 L tickets. At ₹7 L, futures are slightly cheaper per side, but their STT is double.
   - The protocol's 3.7 bp per side slightly under-charges the sell side (3.9 bp). That makes the numbers about 0.2 bp per trade **too kind**; no verdict changes.

## How this changes the picture of the whole project
- **18 locked tests (16 earlier + v1 + v2) found no strategy that passes.** But v2 shows *where* the money goes:
  - **The NFCE signals** (gross +0.05R) and **the stocks-in-play breakout** (gross +10–13 bp) both have small, real gross edges.
  - **Both are eaten by execution:** spread, impact, STT.
  - **The indicator choice is not the bottleneck.** 2,232 indicator rules had a median gross of zero, and the best literature ideas reach about breakeven.
- **Market orders on intraday breakouts pay the full cost of a round trip.** Professional desks that profit intraday mostly *earn* the spread (passive limit orders, rebates, very low fees) rather than pay it. A retail account cannot fully do that, but it can stop paying the full spread.

## The plan: how to use the engine to look for profit honestly
**What is guaranteed:** nothing. SEBI's numbers (91% of traders lose; 0.5% profitable five years running) are the base rate. What follows is the highest-value order of work.
1. **Measure passive execution on the stocks-in-play breakout. This is the best lead, and it needs no new indicator.**
   - **The gap:** H2's gross edge (+10 bp) is about the size of its market-order costs (12.6 bp). A limit (stop-limit) order at the breakout level, which pays fees but not the spread, would cost about 5–6 bp.
   - **The catch:** limit orders do not always fill, and the ones that fill are often the worse trades (adverse selection). That cannot be backtested from candles.
   - **Proposal:** a new strategy paper account **SIP** that places H2's trades as limit orders against the live order book, which the bridge already streams, with ₹3 L cash-equity tickets. Register it before it starts. Judge after **40 sessions** on fill rate, the net bp of filled trades, and the missed winners. Only if it passes, a one-shot check on 2025–26 with the measured fill model; that sample is still untouched for H2.
   - This needs bridge code, so it is the **main session's / owner's decision**, made after the close (no changes in market hours).
2. **Cost-aware sizing:** use the recorded depth to choose each stock's ticket size so that impact stays at or below 3 bp per side (₹1–3 L for most stocks). Brokerage is flat ₹20, so very small tickets are worse. `study2.depth_cost` already does the arithmetic.
3. **The panic-open rebound (H7's real content):**
   - market-wide gap-downs on news days rebounded on most such days;
   - this is a rare event (a few a year), so 5 years cannot prove it;
   - if it is pursued, it should be **one NIFTY futures trade** (cheap) on days when, for example, more than 60 F&O stocks gap down by ≥ 2%;
   - it should be registered now and judged forward over years, with small size. **No claim until then.**
4. **News + LLM, done properly, forward only:**
   - **Source:** NSE's corporate-announcement feed (official and time-stamped) plus market headlines. The LLM scores each item when it arrives; the score and time are logged before any price move is looked at.
   - **Use:** as a filter on "stocks in play" (in play *because of* news vs. without news).
   - **Judge:** after 40 sessions.
   - **Historical point-in-time news** (for example GDELT) could be backtested only with a simple word-list scorer, never with an LLM, because the LLM already knows how those days ended.
5. **Options on the one proven skill:**
   - the range model's next-hour forecast skill (R² ≈ 0.31) is the only measured edge in the project;
   - buying volatility (long straddles) when the forecast range is well above what the option prices imply is a design that uses it without option selling;
   - it needs the R1 option-quote history that the bridge has been collecting since 21 Oct;
   - evaluate it when about 60 sessions exist.
6. **Keep the instrument honest:**
   - every new idea goes in as a hypothesis function in `study2.py`, with a protocol hashed first, a development gate, and a one-shot final;
   - 2025–26 is still untouched for H1–H6 and H8, so keep it for the execution-improved versions;
   - keep recording depth quotes daily; after 5 full sessions, update the friction constants for all studies.

**What would be "taking a loss call like a stupid":** switching on H7 because it made +0.121R in 2025–26. Two days made all of that. Calling it profitable would be exactly the hindsight this protocol exists to prevent.

---

## Correction, 26 Oct 2026 (afternoon, GS phase 0): H1–H3 open-entry cost (appended; nothing above was rewritten)
**The fault** (review A finding 1, confirmed in the code): `orb_candidates` passed an all-false `open_entry` array to `stock_cost`, so an ORB entry in the 09:21, 09:24 or 09:27 bar paid the normal slippage (3.7 bp per side) instead of the open rate (5.0 bp, `EQ_SLIP_OPEN`), which the registered model charges every other entry before 09:30. Fixed (`study2.ORB_OPEN_COST_FIX = True`; `False` reproduces the run above); test `test_orb_entries_before_0930_pay_the_open_slippage`.
**Re-score:** the development stage (2022–24) only, H1–H3, with `tools/study2_rescore.py` (cache `study_engine2/dev_corrected.pkl`). The final (2025–26) was never run for H1–H3 and is not run now. Same trades; 67% of them entered before 09:30.

| Hyp | n | Net R before → after | Net bp before → after | Cost bp before → after | 95% day-block CI (after) | p(day) after | Gate |
|---|---:|---|---|---|---|---:|---|
| H1 | 11,296 | −0.817 → **−0.848** | −23.8 → **−24.7** | 12.6 → 13.4 | −0.900 … −0.798 | 1.00 | fail → fail |
| H2 | 11,296 | −0.018 → **−0.025** | −2.6 → **−3.5** | 12.6 → 13.4 | −0.053 … +0.003 | 0.95 | fail → fail |
| H3 | 2,599 | −0.005 → **−0.011** | +0.9 → **+0.1** | 12.6 → 13.4 | −0.066 … +0.042 | 0.73 | fail → fail |

**Verdicts unchanged:** all three still fail the development gate, now by a little more. H2's gross edge (+9.9 bp) is unchanged; the market-order net is about **−3.5 bp**, not −2.6 bp. Every later document that quotes "−2.6 bp" for H2 should read −3.5 bp.

**Exploratory split (NOT evidence; computed after GS-SIP-1 was designed, on development data, a subgroup):** H2 trades by entry time:

| H2 entry bar | n | Gross bp | Net bp (market orders) | Net R |
|---|---:|---:|---:|---:|
| before 09:30 | 7,620 | +6.3 | −7.6 | −0.053 |
| 09:30 or later | 3,676 | +17.5 | +5.0 | +0.033 |

This is consistent with GS-SIP-1's choice (made earlier, for spread reasons) to start triggers at 09:30, but a post-hoc subgroup of a failed hypothesis is a hint, not a result. GS-SIP-1's own rule also differs (a 3-minute *close* beyond the range from 09:30, which includes stocks that broke out earlier). Only the forward GS-SIP-1 test can say anything.

