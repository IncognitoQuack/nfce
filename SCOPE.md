# Scope: what this system is good for, and what it is not

The lists below describe what the measurements show (20 Oct 2026). Nothing works "perfectly": every claim below has a number, the data it came from, and its limits.

## A. What it does well (measured on data it was not built on)
| Capability | Evidence | Limits |
|---|---|---|
| **1. Forecasting the size of the next hour's move (range), NIFTY / BANKNIFTY** | On fresh Aug–Oct 2026 data: R² 0.31 on log range, against 0.08 for a seasonal rule; pinball 12% lower than seasonal and 8% lower than VIX-only. Skill has held since 2025: 2025 validation R² 0.33, Jan–Jul 2026 0.37, Aug–Oct 0.31 | **Level with a simple linear HAR+VIX model, not better.** 80% bands are a little narrow: they held 77% overall, 75% on NIFTY and about 69% after 13:00. It forecasts size, not direction. Being judged live (R6) |
| **2. Exact TradingView ↔ Python reproduction** | 5,000-bar exports on NIFTY1! 5m and BANKNIFTY1! 15m: every indicator, 13/13 and 25/25 signals, the whole position path, and **every trade's entry, R, P&L and exit within one tick** | Two charts and periods; the TradingView free plan limits history |
| **3. Honest, cost-aware signal vetting** | Every alert carries its out-of-sample record. Index signals use index-futures evidence only (94 trades). It shows the exact cost share of the signal's risk and a trust label from a fixed rule | That evidence is a hold-out record, not a calibrated probability |
| **4. Realistic paper execution** | Live bid/ask with slippage; whole lots (4/3/3); freshness judged at the moment of decision; one position per index and timeframe, enforced atomically; unresolved trades never booked as profit | It is paper trading: queue position and partial fills are approximated (touch-size flag) |
| **5. A research protocol that resists self-deception** | Rules frozen and hashed before data; train / validate / one-shot test; day-block statistics; one α family; one look; 249 automated tests, including fuzzing, failure injection and the reviewers' own failure scenarios | Hashes prove identity, not timing (timestamp them externally) |
| **6. Live data collection for open questions** | Option bid/ask, OI and IV for the eligible expiries and strikes (R1); paired range-target trials (R4); range forecasts scored every 15 minutes (R6) | Answers need months of sessions |

## B. Measured and NOT working (do not use it for these)
| Use | Result |
|---|---|
| Profitable intraday futures trading with NFCE signals | TradingView futures: −0.20R per trade at current costs (94 trades). Simulations: −0.29R (504 trades) and −0.32R (260 trades) |
| Predicting direction (up or down in the next hour) | Machine learning on 1.09 million samples: a coin flip (AUC ≈ 0.50–0.54) |
| The ChatGPT and Gemini report strategies, adapted to futures | 22 configurations: 0 validated; R5 (the best one) failed its one-shot test |
| High win rates or "guaranteed" results | Never measured, never claimed. The best index-futures class wins about 45% of trades |

## C. Not yet known (being measured, decided by pre-registered rules)
- Whether **ITM option execution** turns the small gross edge into a net one (R1).
- Whether **range-sized targets** beat fixed 1R/2R/3R targets (R4).
- Whether the **option-chain veto** separates good signals from bad (R3).
- Whether the range models are **calibrated live**, and which is best (R6).

## D. Out of scope
- **Placing orders.** There is no order code anywhere. Automated orders would need broker approval and algo tagging under NSE rules.
- **Investment advice.** Recommending trades to others in India needs SEBI Research Analyst registration.
- **Stocks** (the evidence cards are index-only for live use); expiries and instruments other than NIFTY / BANKNIFTY futures and their weekly or monthly options.

## E1. After the second live day (22 Oct)
- **The day:** the 5L account lost −₹10,835 (−2.17%; 9 trades, 2 winners). Stock 3m signals: 20 trades, 2 winners. Every signal at ₹1 L risk would have lost about ₹23 L.
- **Why:** most stopped trades never recovered (21% later reached T1), so it was direction, not stop width. Almost every signal was a SELL, and they fired in clusters: one market-wide bet repeated.
- **Leads tested on history, before use:**
  - a same-direction cap: FAILED (it softens the worst days but cannot fix a losing signal);
  - scanner SELL-only: FAILED (−0.065R per trade over 10,708 trades);
  - morning-only stock signals: FAILED (−0.224R on 210 stocks);
  - trading only with the index: FAILED (−0.260R);
  - a second model choosing the trades (meta-labeling): FAILED (2025 −0.327R, AUC 0.511).
- **Wider stops (2×/3×/4×):** they cut the loss from −0.27 to −0.03R per trade, but never to a profit. At 4× most trades ride to the close.
- **Weekly trend-following (time-series momentum) on 213 F&O stocks:** the 12-month version passed 2019–24, then lost 5.2% in its one look at 2025. Not an edge here.
- **Opening gap / GIFT Nifty (25 Oct):** following the gap loses (−0.14%/day); as a filter it helps a little, but not into profit. GIFT Nifty is not added.
- **The common cause:** the entries' drift is real but smaller than the futures round trip. Only cheaper execution (options) can change that, and it can only be measured live: WIDE (2×) and WID4 (4×) do so from 23 Oct.
- **From 23 Oct:** five strategy paper accounts on the same signals (base, concentrated, wide stop, confirmation, cluster cap), judged after 20 sessions. They compare ways of handling signals that test negative. None is expected to be profitable, and none is claimed to be.

## E0. After the first live day (21 Oct)
- **Scanner:** a watchlist, not a trade list.
- **Stock 3m signals:** information only (tested: −0.34R as futures); the paper account takes their options at ¼ risk.
- **EARLY mode:** cannot fire (tested: 0 signals in 4.5 years); replaced by the 09:21/09:30 opening watchlist.
- **Paper account:** a ₹5 L account trades the NIFTY/SENSEX signals as options at 1% risk. Nothing here is proven profitable; the account measures it.
- **Stock signals on 15-minute bars:** also fail (−0.18R per trade, 4,056 trades; `stock15m_result.md`).
- **The account's loss-avoidance rules** (cost gate, one position per underlying, premium cap, loss-streak pause, premium stops) are risk controls chosen in advance, not a measured edge.
- **The Telegram bot runs on its own:** admin and user roles, admin control of the account and features, phone sign-in, a watchdog and scheduled reports. Plain-English answers come from keyword rules, not from an AI model.

## E. The owner's requests of 20 Oct 2026, and where they stand
| Request | What the system does now | Measured? |
|---|---|---|
| NIFTY 50 calls/puts with entry, SL, targets | The bridge runs the NFCE engine itself on live NIFTY futures candles (`ENGINE_UNDERLYINGS`), with no paid TradingView needed. Every signal gets the futures levels **and** the 1-ITM option to buy (call for BUY, put for SELL) at the live ask, with delta-mapped SL/T1/T2/T3. Both are paper-traded | The NIFTY futures signals lose −0.20R per trade after costs (94 trades). Option execution is unmeasured: that is R1, now collecting |
| SENSEX calls/puts | The same for SENSEX: BSE future, BSE option chain, Thursday expiry | **Never tested on SENSEX.** The card shows the NIFTY/BANKNIFTY record and says so |
| Top 5 gainers of the day, F&O stocks only | Scanner over all ~246 F&O stocks at 10:15, 11:15 and 13:15: top 5 gainers and top 5 losers | 2022–24, 50 stocks, current costs: **−0.07R per trade, 7,135 trades → NO EDGE** |
| Other stocks with rising volume | The same scan: top 5 by volume vs the usual volume by that time (≥ 1.5×), traded with the day's direction | **−0.05 to −0.09R per trade → NO EDGE** |
| Entries for stock futures and options, with SL and targets | Every scanner pick: futures levels (SL 0.5 × ATR, T1/T2/T3 = 1/2/3R) and the 1-ITM stock option (skipped when its spread is above 5% of the premium); paper-traded | The futures rule is the one tested above; options are unmeasured |
| Both possibilities, buy or sell, call or put | BUY → buy the call; SELL → buy the put; losers are SELL signals | **Option selling (writing) is not supported:** unhedged, the loss is unlimited |

The system does what was asked, and labels each item with what has been measured. **Nothing here has been shown to make money after costs.** The scanner was tested before it was built, and it failed.

## F. How to benchmark another model against this system
1. **Same target and data:**
   - Use the 19 live features (`nfce_engine/tools/train_range_model.py: LIVE_FEATURES`) and the target `R60` (log next-hour range).
   - Use the same decision bars (closes 09:45–14:15, every 15 minutes).
   - Use the same splits: train 2022–24, validate 2025, test 2026, fresh Aug–Oct 2026.
2. **Same scoring:** `nfce_engine/tools/range_benchmark.py` gives pinball loss, band coverage, R², time-of-day splits, and day-block intervals against the incumbents (M1, HAR+VIX, seasonal, VIX-only).
3. **A trading model:** to test one, score it the same way the strategies were scored:
   - next-bar fills, stop before target, current (2026) costs;
   - train / validate / one-shot test;
   - `nfce/stats.py: report` for day-block intervals.
4. **Register before you look:** write the rules down, hash them, run the test once, and report every number.
