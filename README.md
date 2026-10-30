> **Public release.** This is a sanitized copy of a private research project. Live trading logs, daily reports, market data, credentials and personal files are removed, so a few references below (e.g. `LIVE_DAY_*.md`, `evidence/ledgers/`) point to files that are not included. Code, tests, protocols, pre-registered results and the changelog are complete. Built with Claude Code. Research software only: it places no orders and is not investment advice.

# Final Trade Software: NSE F&O Intraday Research & Paper-Trading System (NFCE), v3

**Final package, 20 Oct 2026.** Research and paper-trading software for NIFTY and BANKNIFTY intraday trading. It places no orders and gives no investment advice.

**New in v3.3 (after the first live day, 21 Oct):**
- **Paper account:** a ₹5 L account with real constraints (risk sizing, cash, limits, ledger, `/account`).
- **Scanner:** a watchlist, not a trade list.
- **Stock 3m signals and EARLY mode:** tested and failed, so they are information only.
- Full record: `LIVE_DAY_2026-10-21.md`; studies: `evidence/stock3m_result.md`.

**New in v3.1 (the owner's requests):**
- **No paid TradingView needed:** the bridge computes NIFTY and SENSEX signals itself from live Upstox futures candles.
- **Option legs:** every signal shows the call or put to buy, with entry, SL and targets, paper-traded at the real bid/ask.
- **F&O scanner:** top gainers, losers and volume surges across all F&O stocks, with levels and paper trades.
- **Tested before it was built:** the scanner's rules lose after costs (`evidence/scanner_result.md`), and each scan message says so.
- Item-by-item status of the requests: `SCOPE.md` section E.

**New in v3:**
- **All 24 findings fixed:** the round-3 independent review's findings were all confirmed and fixed test-first, with 33 of 34 new tests failing on the old code (`evidence/review_round3_response.md`).
- **Range-model benchmark:** a new benchmark on fresh data (`evidence/range_benchmark_result.md`).
- **R6:** a new live forward benchmark of the range forecasts.
- **Ledgers and data manifest:** per-trade ledgers for every study, plus a checksummed data manifest (`evidence/ledgers/`).
- **Scope:** an explicit statement of what the system is and isn't good for (`SCOPE.md`).

## The verdict first
**No strategy tested here is shown to be profitable at 2026 Indian trading costs.** That covers:
- NFCE, the original 9-factor confluence engine: −0.20R per trade on 94 TradingView futures trades at current costs;
- 84 configurations of opening-range, momentum and VWAP rules, on 4.5 years of data;
- a machine-learning direction study on 1.09 million samples, which was a coin flip;
- 22 adaptations of the ideas in two outside AI research reports (ChatGPT and Gemini): 0 validated, and R5 failed.

Each was tested on data it was not designed on.

**What the system does well** (details and limits in `SCOPE.md`):
1. **It forecasts the size of the next hour's move.**
   - On fresh Aug–Oct 2026 data the model had never seen: R² 0.31, and pinball loss 12% below a seasonal rule and 8% below a VIX-only rule.
   - That skill has held for three periods in a row.
   - Honestly: it is *level with* a simple linear HAR+VIX model, not better. Its 80% band holds about 77% of moves, and about 69% after 13:00. R6 judges this live.
2. **It reproduces TradingView exactly.** Indicators, signals, the whole position path, and every trade's entry, risk, P&L and exit, within one tick (13/13 and 25/25 trades).
3. **It never fools its owner.** Every signal carries its measured, out-of-sample record; index signals use index-futures evidence only. The card shows the exact cost share and a trust label from a fixed rule. Paper trades use whole lots, live bid/ask, decision-time freshness and atomic one-position entry, and are never invented.
4. **It measures what is still unknown.** Option execution (R1), the option-chain veto (R3), range targets (R4) and range calibration (R6) are each decided by rules frozen before the data.

**Why trading costs decide everything:**
- **The cost:** since 1 April 2026, STT on futures is 0.05% of notional, so a NIFTY futures round trip costs about 15.7 index points (an independent reviewer got the same figure).
- **The edges:** the best intraday edges found are +0.1 to +0.2R *before* costs, which is less than that.
- **The open question:** cheaper execution through ITM options, now being measured live (R1).

## What is in the package
| Part | What it does | Status |
|---|---|---|
| `nfce_indicator.pine`, `nfce_strategy.pine` | TradingView indicator and strategy (Pine v6): entry, SL, T1–T3, dashboard, JSON alerts | Python engine = TradingView, bar by bar and trade by trade |
| `nfce_bridge/` | Upstox data → option-chain check → evidence card + range forecast → Telegram alerts → paper books → live scorecards | Live-verified with a real Upstox account and Telegram bot (first live session 21 Oct 2026, see `LIVE_DAY_2026-10-21.md`); **185 tests** |
| `nfce_engine/` | Python port, research tools, simulations, ML study, range benchmark, scanner research, registry scoring | **108 tests** |
| `evidence/` | Every protocol (frozen before its results, with SHA-256), every result, per-trade ledgers, data manifest | See the list below |
| `REGISTRY.md` | Current registration v3: R1–R4 (one α family), R5 (closed), R6; 21 frozen file hashes | All current hashes verify |
| `SCOPE.md` | What it is good for, what it is not, how to benchmark another model against it | — |
| `docs/` | Original spec, the round-1 reviews, the round-2 ChatGPT and Gemini reports, the round-3 review | — |

## Evidence index (each protocol was frozen before its results)
| Study | Result | File |
|---|---|---|
| NFCE on TradingView futures (94 trades) | −0.17R per trade at dated costs, −0.20R at current costs | `PHASE7_V2_EVIDENCE.md`; the bridge's `evidence_table.json` |
| 504 simulated NFCE trades on 28 unseen sessions | −0.29R per trade; the "morning edge" came from stocks, and index futures in the morning lose (−0.25R) | `evidence/holdout_result.md`, `ledgers/holdout_504_trades.csv` |
| 84 configurations, 4.5 years, train/validate | 21 train survivors, 0 validated; all negative at current costs | `evidence/research_result.md`, `ledgers/research_84_trades.csv` |
| ML: direction, range, target-before-stop (1.09M samples) | direction: coin flip; range: passes | `evidence/ml_result.md` |
| Range benchmark on fresh Aug–Oct 2026 | ties the linear HAR+VIX model; beats seasonal and VIX-only; bands slightly narrow | `evidence/range_benchmark_result.md` |
| ChatGPT and Gemini adaptations (22 configurations) | 0 validated; R5 one-shot fail; a corrected re-run changed 0 of 9,561 trades | `evidence/external_result.md`, `ledgers/external_S1_S9_trades.csv` |
| Bar-by-bar and trade-by-trade parity with TradingView | PARITY: indicators, signals, position path and trade ledger (13/13, 25/25) | `evidence/golden_parity_*.txt` |
| F&O scanner rules (gainers, losers, volume surges), 9 configurations | all lose after costs in 2022–24 (−0.05 to −0.10R); not continued | `evidence/scanner_result.md` |
| Round-3 review response | 24 of 24 confirmed and fixed; published numbers moved by at most 0.002R | `evidence/review_round3_response.md` |

## How a signal looks
```
🔴 NO EDGE: NIFTY BUY A
Chain check: ✅ PASS
Entry 25,000.0  SL 24,960.0  T1 25,040.0  T2 25,080.0  T3 25,120.0 | 5m score 72
... option-chain summary ...
Evidence (index futures / morning / current costs, unseen sessions): n=38 trades, 45% winners, before costs +0.02R, after costs -0.25R [95% -0.54..+0.05]
Costs for this signal: 38% of its risk (morning entry)
Note: index futures only; the hold-out simulation had just 24 index trades, so it is not used
Why NO EDGE: no meaningful edge even before costs
Next-hour range forecast (R4 model): median 62 pts, 80% band 41-110 pts (from the 10:00 bar)
executable book: entered 10 lots at 25000.3 (ask + 2 ticks, decided 5s after the bar) | r4 book: entered ... with range targets ...
Alerts only. No order placed. Not a recommendation.
```

## Run it
```bash
cd nfce_bridge && bash setup.sh                     # venv, pinned packages, tests, .env check
.venv/bin/python -m bridge.check_setup              # every line [ok]: keys, Telegram, Upstox, timestamps, both range models
bash start.sh                                       # each market day: sign in to Upstox in the browser
```
- **Telegram commands:** `/check BUY 24512 24480`, `/status`, `/paper`, `/options`, `/scan`, `/trust`, `/range`, `/health`, `/halt`, `/resume`.
- **Scoring the experiments:** `nfce_engine/tools/registry_eval.py r1|r2|r3`, `registry_eval_r4.py` and `registry_eval_r6.py`. Each prints PASS / FAIL / INCONCLUSIVE, or NOT YET.

**Reproduce the research:**
```bash
cd nfce_engine && pip install numpy==2.5.4 pandas==3.0.6 scikit-learn==1.9.1 scipy pytest && python -m pytest -q   # 108 passed
```
- **Market data is not included** (Upstox and Yahoo terms).
- **What is included instead:** every derived per-trade ledger, and `evidence/ledgers/data_manifest.json`, which gives the SHA-256, row count and date range of every raw data file used.
- **Re-downloading:** `tools/fetch_yahoo.py` re-downloads Yahoo data; the Upstox commands are in `evidence/research_protocol.md`.

## Honest limitations
- **Spot index as a futures proxy** in the multi-year studies: no basis or roll. TradingView parity was proven on real futures.
- **No historical option prices or OI.** Option strategies can only be measured going forward (R1 records live bid/ask).
- **Upstox historical candles can lag a day.** The bridge checks the history against the official previous close and refuses to forecast until it catches up.
- **Paper fills** approximate the queue and size: they flag when the touch size is below the order.
- **Registration timing:** hashes prove files are unchanged, not when they were written. Timestamp `REGISTRY.md` outside this package.
- **Not investment advice.** Giving trade recommendations to others in India generally requires SEBI Research Analyst registration.

## For reviewers
See `EVALUATOR_PROMPT.md` (round 4). The most useful review challenges the verdict in either direction, with evidence.
