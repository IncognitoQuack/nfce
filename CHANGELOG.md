# Live chart with indicators, review of the owner's manual trades (28 Oct, ~22:00–22:40)
**Test counts:** engine 342, bridge 289 (+3). `nfce verify` passes. Today's EOD report regenerated without data problems.

| Change | Evidence / test |
|---|---|
| **Chart on the Trade tab:** 1-minute candles of any index root or F&O stock from the live stream (5 s refresh), VWAP (stocks: volume from the cumulative traded quantity), EMA 9/21, RSI 14, the day range, and every signal of the day drawn at the spot price of its minute with its stop and T1 (futures levels moved by the same distances, as the alerts do). Click a signal's underlying, or "Use", to chart it. A readout line states the indicators as descriptions, not predictions | `test_chart_bars_indicators_and_signal_levels`, `test_rsi_is_wilder_and_bounded`; browser: RELIANCE 28 Oct, 371 candles, 14:00 SELL at 1164.20 (alert said 1,164.60) |
| **EOD report section 6, the owner's manual trades:** each MAN trade's buy/sell time, held minutes, net after costs, best open P&L while held, given back, whether it followed a system signal (same underlying and direction, ≤ 15 min before) or was the owner's own idea, and the exit. Plus any MANUAL overrides in the strategy accounts | `test_eod_reviews_the_owners_manual_trades` |

# Ready for the owner's manual trading on 29 Oct: bug review, real-wiring check, signals panel (28 Oct, ~21:30–22:00)
**Test counts:** engine 342, bridge 286 (+2). `nfce verify` passes.

| Change | Evidence / test |
|---|---|
| **Bug: two manual buys in the same second shared one position id** (the second overwrote the first). Fixed with a suffix; the lookup runs under the store lock | `test_two_manual_buys_in_the_same_second_keep_separate_ids` |
| **Bug: Telegram `/open` would print a manual position's stop as "−1,000,000,000,000.00".** It now says "manual position: no automatic stop or target" | bot tests green |
| **`/api/live` fails part by part:** a broken query no longer blanks the Trade tab; the errors show next to the clock | `test_live_snapshot_survives_a_missing_table` |
| **Signals panel** on the Trade tab: today's signals (stock3m / index / scanner) with entry, stop, T1, the system's live check (NO_DATA in amber), the futures-book result so far, and **"Use → CALL/PUT"**, which fills the MAN ticket. Positions show **Held** minutes (amber at 30) | browser: 50 real signals rendered; synthetic MAN position rendered with Sell, amber 31 min, Use→PUT filled the ticket; 1 s refresh confirmed |
| **Real-wiring integration check** (real `.env`, a copy of today's DB, the real app; no Telegram, no network): **8 accounts** load (G20 ₹20 L guarded, MAN ₹5 L manual); the admin API refuses no secret (403) and a manual buy in 5L (403); pause/resume work | run in the session |
| `TRADING_NOTES_2026-10-29.md`: an evidence-only sheet for the owner's manual trading | — |

# CAL-1: published calendar effects on 20 years of NIFTY (28 Oct, ~21:00–21:30)
**Test counts:** engine 342 (+2), bridge 284.

| Change | Evidence / test |
|---|---|
| Web search for evidence-backed effects not yet tested here (≈50 registered tests so far). Turn of the month: Mangala & Sharma 2007, Satish & Bheemanagouda 2023 (Nifty). Pre-holiday: Lakonishok & Smidt 1988. **CAL-1 registered and run.** Both effects are positive after costs on 2006–15 (+48 / +19 bp a trade), but **not significant** (p 0.053 / 0.068 vs 0.025 required). FAIL; later years untouched | `evidence/cal_1_result.md`; `tests/test_cal_1.py` (2) |

# Desk Trade tab, the owner's manual account MAN, 1-second live view (28 Oct, ~17:55–18:20)
**Test counts:** engine 340, bridge 284 (+4). `nfce verify` passes. The frozen files are untouched.

| Change | Evidence / test |
|---|---|
| **MAN, the owner's own ₹5 L paper account** (`ACCOUNTS=…,MAN:500000:manual`): strategy `manual` takes **no signals**. The owner buys and sells from the desk: `Account.manual_buy` (lots chosen by the owner, at the ask, cash-checked, 09:15–15:10) and `Account.manual_sell` (some or all lots, at the bid). No automatic stop or target; the 15:15 square-off applies. Not a strategy test; its fills say "MANUAL …" | `tests/test_manual_account.py` (4) |
| **Admin API:** `buy` (**only** in a `manual` account; 403 for every strategy account) picks the 1-ITM option with the engine's own `pick_leg` (same strike rule and spread check); `sell` (partial); `GET /admin/universe` (index roots + the stock engine's F&O stocks) | same file; `test_admin_api.py` updated |
| **Desk Trade tab:**<br>an account filter (All / each account);<br>live equity, cash and open P&L per account;<br>open positions marked from the **stream every 1 s** (bid, P&L, peak, given back, tick age), each with **Sell** (all or N lots);<br>**today's trades per account** (time, side, contract, lots, price, realised, reason);<br>the **MAN order ticket** (underlying, lots, Buy CALL / Buy PUT; control role only) | live check in the browser pane: CONC's 8 fills shown with prices and reasons |
| **`/api/live`:** a light endpoint for the 1 s refresh (~14 ms round trip; 0.5 ms to build). The heavy snapshot stays at 5 s. **The registered accounts still evaluate exits on the bridge's 15 s loop** (QUOTE_SECONDS=15). Faster would exceed Upstox's ~2,000 requests/30 min with 8 accounts; the stream-driven exits are plan L1/L3 work | — |
| Owner asked "take the opposite trade": already tested 27 Oct on 16,598 trades. Reversed −0.37R vs −0.27R: worse, because costs hit both directions. Not built | `evidence` (27 Oct) |

# SMART-EXIT-2 (owner's tight-stop rule) and the G20 "guarded" ₹20 L account (28 Oct, ~17:10–17:50)
**Test counts:** engine 340 (+1), bridge 280 (+4). `nfce verify` run after these changes.

| Change | Evidence / test |
|---|---|
| **SMART-EXIT-2 registered and run** (book +0.3/+0.5R with a stop at −0.15/−0.25/−0.5R; breakeven variant). **All FAIL**: −0.335 to −0.352R, negative even before costs, because the tight stop is touched first ~2× as often as the target | `evidence/smart_exit_2_result.md`; `tests/test_smart_exit.py::test_smart_exit2_tight_stop_walker` |
| **New account G20** (₹20 L, `ACCOUNTS=…,G20:2000000:guarded`, the owner's request): strategy `guarded` = base + the 30-min time stop + a 15% cost gate + no index entry without a fresh futures quote (`Account._futures_fresh` uses the bridge's own `fresh_quotes`). Quiet. Starts at the 29 Oct `nfce start`. **Risk controls, not a measured edge** | `tests/test_account_guarded.py` (3); `evidence/guarded_account_protocol.md` |
| **Per-account capital** in the EOD report (`eod_report.capital`) and on the desk (account cards; the performance chart is now % of each account's capital). A fixed ₹5 L base would have shown G20 at +300% | `test_performance_uses_each_accounts_own_capital` |

# Control desk v3 + `nfce verify` (28 Oct, after the close, ~16:30–17:30)
**Test counts:** engine 339, bridge 276 (+7 since the day entry below). `nfce verify` passes. The frozen files match (`bridge/config.py` was briefly edited, caught by verify, and reverted to its registered hash `8026a4e8…`). Owner decisions 28 Oct ~13:55: LAN desk with tokens, full audited controls.

| Change | Evidence / test |
|---|---|
| **Desk on the Wi-Fi** (`ops/desk.py --lan`, now in the runbook): `/api/*` needs a token from any other device. VIEW is read-only; CONTROL can act. This Mac needs none. The page holds no data. Phone links (with tokens) are shown only on the Mac's own screen (System tab). Tokens are in `.env` (`--init-tokens`; never printed; the package refuses secrets) | `test_roles_tokens_and_the_wifi_rule`, `test_remote_needs_a_token_and_view_cannot_control`; live: Wi-Fi without a token 401, VIEW 200 + control 403, CONTROL 200 |
| **Desk controls:** close one position in ONE account; close all in one account; pause/resume an account; HALT ALL / RESUME ALL. Each needs a confirm dialog. They relay to the bridge's new **local-only admin API** (`bridge/admin_api.py`, `DESK_ADMIN_SECRET` read from `.env`). Every call is written to `events` before and after it acts; exits are sold at the live bid with reason "MANUAL …". **Fixes:** Telegram `/close <n>` closes position n in every account | `tests/test_admin_api.py` (5, incl. a real `Account` closed end to end) |
| **Account lock:** `Account.on_tick`, `consider` and `close` take a per-account lock (the poll loop, Telegram and the desk could act on one account at once) | suite green |
| **Giveback column:** the Risk tab shows each position's peak open P&L since entry (best stream bid) and how much has been given back | live render |
| **Control log** (System tab): every desk and Telegram admin action today | live render |
| **Phone layout** (≤ 640 px): 2-column cards, no sideways scroll at 375 px | browser check |
| **`nfce verify`:** compile sweep, imports, both suites, preflight (frozen files, database, ledgers; power and token reported only), desk strict-JSON smoke. **Run before any restart** | caught the `config.py` edit on its first run |

# Live day 28 Oct: desk fixes, data-freshness fixes, SH-1 and SMART-EXIT-1, master plan (28 Oct, 08:57–16:30)
**Test counts:** engine 339 (+4), bridge 269 (+5). Frozen files all match; `import bridge.service` OK; RiskGate unchanged. The bridge and the accounts were not changed during market hours; only the desk was restarted (twice, owner OK).

| Change | Evidence / test |
|---|---|
| **Desk 500 on a NaN** (08:57): a "pending" OVN v2 row had `units` NaN, and strict JSON failed the whole snapshot, so every tab went down. `research_section` now sends NaN as blank, and `json_safe()` cleans the whole snapshot before `/api/all` | `test_one_nan_anywhere_cannot_take_the_desk_down` |
| **Desk sign bug** (found 10:40, fixed 11:04): `desk_risk.position_risk` treated `Position.side` (the signal's direction) as long/short, so every put bought on a SELL signal showed as a short with its P&L flipped (the false "6/7 in profit"). The accounts only buy options; units are now always long | `test_a_put_bought_on_a_sell_signal_is_long_and_loses_when_its_premium_falls` (the old test that encoded the bug was replaced) |
| **Desk alerts:** warn/info dismiss with × or auto-hide 30 s after first seen; crit always stays; "show N hidden" brings them back (`ops/desk.html` only) | checked live in the browser pane |
| **Runbook order:** `nfce morning` started `track` before the brief wrote `watch_<day>.json`, and it crashed. The brief now runs before any job marked `after_brief` | `test_morning_refreshes_index_bars_and_runs_the_brief_before_track` |
| **Daily bars:** the historical endpoint ends yesterday, so the evening refresh never had the day's bar, and OVN/OPX sat "pending" on 28 Oct morning. `pull_daily.py` gains `--with-today` (the intraday endpoint, after the close; evening runbook) and `--only` (merges `lots.json`; the morning runbook refreshes NIFTY/BANKNIFTY/INDIAVIX). Run at 16:05: 221 symbols to 28 Oct | `tests/test_pull_daily.py` (2) |
| **SH-1** shadow rule + replay `ops/shadow_hold.py`; **SMART-EXIT-1** registered and run (all FAIL) | REGISTRY; `evidence/smart_exit_1_result.md`; `tests/test_smart_exit.py` (4) |
| **`MASTER_SYSTEM_PLAN.md`:** 8-layer plan. Owner decisions: LAN desk with tokens, full audited controls, SMART shadow-first | — |
| Checked and found NOT a bug: the KAYNES future 3–4% below spot all day is a real discount (tight spread, 2.7 M volume), not a feed error | quotes DB |

# Sector impact made test-ready (28 Oct, ~00:35)
**Test counts:** engine 335, bridge 264 (+1).

| Change | Evidence / test |
|---|---|
| `ops/signal_context.py` reads an OPTIONAL `~/Downloads/nfce_data/sector_map.csv` (symbol,sector) and records per signal `sector`, `sector_chg_pct` (the sector peers' equal-weight day change at t, from the stream) and `sector_aligned`. Without the file they stay empty. Bug found by the new test: a blank sector cell became the sector "nan", grouping every unmapped stock together. Fixed (`keep_default_na=False`) | `test_sector_fields_fill_only_when_a_sector_map_is_given` |

# Fresh-eyes bug review of the 27–28 Oct code (28 Oct, ~00:10–00:15)
**Test counts:** engine 335, bridge 263 (+1). Every `.py` in `ops/`, `bridge/`, `nfce_engine/tools/` and `nfx/` compiles. `import bridge.service` OK; RiskGate unchanged; the desk restarted at 00:14 on the final code.

| Finding | Fix / evidence |
|---|---|
| **stream.py: one malformed frame tore down the whole connection** (the decode error reached the outer handler, which dropped the socket and re-authorised) | Bad frames are now skipped and logged (`info.kind = 'bad_frame'`); the connection stays up. `test_a_bad_frame_is_skipped_and_buffered_ticks_survive_a_drop` |
| **stream.py: up to 1 s of buffered ticks was lost on every drop** | The buffer is flushed before reconnecting (same test: the good frame's 3 ticks are saved) |
| **desk.py re-checked the Upstox token every 5 s by starting a Python process** (~4,700 a day) | `system()` is cached for 60 s |
| desk.py re-scored the overnight tracks every 5 min, reading every day's 100+ MB chain file | Cached 30 min (the results only change at 09:20 / 15:20) |
| **My own edit during the review broke `desk.py`** (a comment inserted mid-line swallowed half a dict) | Caught by the suite (2 errors); fixed; a compile sweep over all Python files was added to the checks |
| Checked and found correct: the runbook's 503 handling, never starting a job twice, the evening backup wait; desk marks and signs; the bridge DB is already WAL | — |

# Night of 27→28 Oct: signal context, market regime layer, robustness for the first streaming day (00:00–00:30)
**Test counts:** engine 335, bridge 262 (+5). Frozen files all match; GS FROZEN; `import bridge.service` OK; RiskGate SHA `a3fe0ac8…` (unchanged).

| Change | Evidence / test |
|---|---|
| **`ops/signal_context.py`** (shadow): for every signal, records as of the signal time:<br>stock change, spread, L1 and L2–5 imbalance;<br>NIFTY change, VIX and its change, breadth;<br>NIFTY ATM IV / skew / PCR;<br>news count, minutes since and results flag;<br>the results meeting;<br>the **morning brief's overnight results** (categories, profit and revenue YoY);<br>alignment with the order book, market and breadth;<br>**regime**.<br>Written to `data/signal_context.db`. **Outcomes are deliberately not joined.** Runs inside the EOD report (section 5). 27 Oct: 11 of 32 signals carried brief news (e.g. the scanner sold PAYTM short on profit +971%) | `tests/test_signal_context.py` (2) |
| **`bridge/regime.py`**: live labels, calm / normal / stressed (VIX percentile vs 252 closes, or +8% on the day) × trend up / trend down / mixed (NIFTY ±0.6% plus breadth). On the desk header and stamped on every signal. **Not a trading rule:** a locked test comes first | `tests/test_regime.py` (2) |
| **Robustness:**<br>the stream DB in **WAL** mode (stress test: 3 M ticks, a writer every 0.5 s vs continuous desk reads, 0 lock errors, commits ≤ 17 ms, snapshots ≤ 24 ms);<br>desk stream-health without COUNT(*) scans;<br>the SCALP-1 replay deferred to after 15:20 and cached 30 min (about 14 s on a full day);<br>the breadth query cached 60 s | stress run in the session |
| **Stale desk:** a desk started 27 Oct 19:13 still ran the pre-fix code on :8001. It was restarted, and `runbook morning` now restarts any desk started before today | `test_stale_desk_is_detected_by_its_start_date` |
| **`HANDOVER_FOR_NEW_CHAT.md` rewritten** for 28 Oct: rules, the morning-to-evening runbook, accounts, evidence, research tracks, a coverage map of the owner's factor list, the regime layer, data, gotchas, lessons, agenda | — |

# The `nfce` CLI upgraded; a power-reading bug fixed; full rehearsal for 28 Oct (27 Oct 2026, ~17:10–17:25)
**Test counts:** engine 335, bridge 257 (+2). `nfce check` all ok except the battery; GS FROZEN; `venv_ok` now also checks websockets and protobuf.

| Change | Evidence / test |
|---|---|
| **`nfce` CLI (`bridge/panel.py`), new commands:**<br>`morning` (after `start` + sign-in: the runbook; refuses if the bridge is down);<br>`evening` (stop, candles, EOD report, package; **refuses during market hours** unless `--now`);<br>`jobs` (today's background jobs);<br>`desk` (starts the desk once and opens it);<br>`eod [day]` (writes and shows the analysis);<br>`research` (scores OVN v2/v3, OPX-1, SCALP-1 now).<br>`status` now shows today's jobs. Existing commands unchanged | `tests/test_panel.py` (+1): registered and guarded |
| **BUG FIXED:** `panel.power()` returns *(on charger, %)*, and the desk and runbook read it as *(on battery, %)*. The desk showed "on charger" while on battery, and the low-battery alert could never fire. Found while wiring the CLI | `test_power_is_read_as_on_charger_first` |
| `ops/sigwatch.sh`: the fills-or-signals watcher moved out of the session scratchpad into the project | run once: clean exit |
| **Rehearsal for 28 Oct:**<br>every morning job run for real against scratch files (chain, quotes, news, stream 431/431 with 0 errors);<br>the runbook paths exist;<br>28 Oct is a session with no events;<br>the instruments roll to the Nov stock futures (the early expiries are only currency, commodity and BSE contracts);<br>the chain recorder rolls to NIFTY 3 Nov / 10 Nov;<br>`nfce evening` end to end in 1 min 48 s | this entry |

# Master upgrade, part 1: Desk v2, risk engine, scalping test, EOD analysis, runbook (27 Oct 2026, ~16:45–17:05, after the close)
**Test counts:** engine 335 (+7), bridge 255 (+14). Frozen files all match; GS FROZEN; `import bridge.service` OK.

| Change | Evidence / test |
|---|---|
| **INCIDENT, found and fixed in the same minute:** a new desk module was first written to `bridge/risk.py`, which is the live bridge's **RiskGate** (`service.py` imports it). The bridge would not have started on 28 Oct. It was restored byte-identical (SHA `a3fe0ac8…`) from the 16:35 package, and the new module moved to `bridge/desk_risk.py`. Lesson recorded: check any "new" path first, and import `bridge.service` after every change | `tests/test_service_app.py` passes; suite 245 → 255 |
| **`bridge/desk_risk.py`:** honest marks (a long at the bid, a short at the ask, last trade flagged); position Greeks from Upstox's live option Greeks; a **scenario grid** (Δ·dS + ½Γ·dS² + vega·dIV, spot ±1/2/3%, IV −5/+5/+10); exposure by underlying | `tests/test_desk_risk.py` (4) |
| **`ops/stream.py`:** stores the full option Greeks (gamma, vega, theta; older files upgrade in place) and **follows the book**: every 30 s it subscribes any open account contract and its underlying | `tests/test_stream.py` (+1: book keys) |
| **Desk v2** (`ops/desk.py`, `desk.html`): tabs Live / Risk / Performance / Research / System; an index ticker from the stream; a **rule-based alert bar** (crit / warn / info: bridge down in market hours, silent poll loop, token, battery, GS not frozen, loss limit ≥ 80%, give-back halt, loss streak, silent stream, unmarked positions, a failed section); **every section isolated** on the server and in the browser; research panels cached. KPI fix: futures and options books shown separately (never added: the same signals) | `tests/test_desk.py` (6): risk from a stream file, alert rules, isolation, read-only |
| **SCALP-1** (`evidence/scalp_1_protocol.md`, prior FAIL) + `nfce_engine/tools/scalp_sim.py`: universe (spread ≤ 3 bp, top 30 by value at 09:30), L1 and L2–5 imbalance, passive entry filled only on a strict trade-through within 30 s, stop 8 bp marketable, target 12 bp passive, time 180 s, flat 15:10, 2 open / 40 fills / ₹10k daily stop, real fees. Pre-read: +0.65 bp per minute vs 4.53 bp fees | `tests/test_scalp_sim.py` (7) |
| **`ops/eod_report.py`:** an end-of-day analysis to `reports/EOD_<day>.md`: market, accounts since inception (return, max drawdown, best/worst day, positive days), attribution by book / direction / hour / exit, costs, GS, OVN v2/v3, OPX-1, SCALP-1. Each section is isolated. 27 Oct: the scanner's 14 futures stops −₹1,07,507 vs 8 targets +₹65,671 | `tests/test_eod_report.py` (3) |
| **`ops/runbook.py`:** `status` / `morning` (after `nfce start` and the owner's sign-in: checks the bridge and token, starts the recorders, stream and desk once each, runs the news brief) / `evening` (waits for the 15:35 backup, stops the bridge, refreshes the daily candles, writes the EOD report, rebuilds the package). It never signs in or sends messages | `tests/test_runbook.py` (3) |

# OVN v3: the overnight iron fly centred on the put-call-parity forward (27 Oct 2026, ~16:35; a new sample alongside v2)
**Test counts:** engine 328 (+4), bridge 241. Frozen files all match; `overnight_options.py` (v2) unchanged.

| Change | Evidence / test |
|---|---|
| **Why:** since NSE's closing auction (Aug 2026) the index spot freezes at 15:15, while NIFTY options trade to 15:40. v2 centres its fly on the frozen spot. **v3 centres it on the options market's own forward** (which also includes the carry). Owner-approved as a new sample; v2 continues | `evidence/overnight_options_v3_protocol.md` (SHA `41e4449d…`) |
| `nfce_engine/tools/overnight_v3.py`: `parity_forward` (the median of k + mid C − mid P over the 3 strikes nearest the spot, valid pairs only; none means "no forward: not entered"); `session_v3` / `score_v3` mirror v2 line for line, with only rule 7 changed | `tests/test_overnight_v3.py` (4): forward recovery, invalid pairs, the 27 Oct case (K 22750 vs 22800), no rows before the start |
| Descriptive, 27 Oct 15:20: 3 Nov forward 22,784.8 vs frozen spot 22,760.75 (+24 pts). The expiring contract's forward was 22,816.6 (0DTE distortion; v3 never uses that expiry) | REGISTRY |

# OPX-1: the options-premium module, a range-gated overnight iron fly (27 Oct 2026, ~16:30; forward paper pilot)
**Test counts:** engine 324 (+6), bridge 241. Frozen files all match; GS FROZEN.

| Change | Evidence / test |
|---|---|
| **Design decision (before any data):** the published evidence (Muravyev & Ni 2020; Bhat et al. 2024 on Nifty) says short-option returns are favourable **overnight**, not intraday. So the module sells premium overnight only, through OVN v2 (defined-risk iron fly, ₹5,000 per structure including fees, ₹10 L book, VIX and event gates). OPX-1 adds one gate: **take the trade only when the ATM IV ≥ 1.50 × the range model's ENS forecast volatility.** Ungated OVN v2 is the control, which answers "does the forecast add value?" | `evidence/opx_1_protocol.md` (SHA `93c3dd74…`) + `opx_1_amendment_1.md` (gate n/a when OVN forms no structure) |
| `nfce_engine/tools/opx_gate.py`: causal forecast volatility (the mean of exp(q50) over the day's ENS rows ÷ √(8/π) × √(252 × 6.25)), entry-snapshot IV of the K call and put, the gate, the gated units, the pilot report with `gs/evaluate.pilot_decision` | `tests/test_opx_gate.py` (6) |
| Daily candles refreshed to 26 Oct (`ops/pull_daily.py`, 216 symbols). OVN v2 for 27 Oct: **skip (VIX gate)**, so OPX-1 is n/a. The first possible entry is 28 Oct 15:20 | REGISTRY |

# Streaming market data (shadow): Upstox Market Data Feed V3 over WebSocket (27 Oct 2026, ~16:20, after the close)
**Test counts:** engine 318, bridge 241 (+4). The bridge itself is unchanged. New packages (owner-approved): `websockets` 17.3, `protobuf` 7.36.2. numpy, pandas and scikit-learn are unchanged, and GS-SIP-1 still verifies FROZEN (its lock covers only those three).

| Change | Evidence / test |
|---|---|
| **`bridge/proto/MarketDataFeedV3.proto`:** Upstox's official file from `https://assets.upstox.com/feed/market-data-feed/v3/MarketDataFeed.proto` (linked from the V3 feed docs; there is no official GitHub copy). SHA-256 `3e1c939d…f612`. It includes closing-auction fields (`iep`, `casEligible`, `casMarketStatus`) | `test_proto_file_is_the_verified_official_one` |
| **`bridge/feed_proto.py`:** builds the 14 V3 message classes **at runtime from that file** (a small proto3 parser to a FileDescriptorProto). No protoc and no downloaded generated code. Refuses to decode if the file's hash changes | `test_every_field_of_the_official_proto_is_built_with_its_number_and_type` (every message and field number checked against the file) |
| **`ops/stream.py`:** the shadow recorder. Authorize (`/v3/feed/market-data-feed/authorize`), then a one-time wss URL, a **binary** JSON subscription (431 keys: each F&O stock's equity and front future, the NIFTY future, NIFTY / Bank Nifty / SENSEX / India VIX; `full` mode; 1 of the 2 allowed connections). Then protobuf frames into its own DB (`tick`: last trade and times, 5-level book, volume, OI, ATP, total buy/sell qty, IEP, CAS flag, IV/delta; `info`: market status, errors, summary). It re-authorizes on every reconnect, with backoff up to 60 s | `tests/test_stream.py` (frames to rows for all three feed shapes, market info, binary subscription, schema) |
| **Live connection test (16:17, market closed):** authorized, connected, 431/431 instruments in the snapshot, 0 errors. Status NSE_EQ = CLOSING_END, NSE_FO = NORMAL_CLOSE. NIFTY's auction close is 22,749.75 (the screen showed 22,760.75 frozen at 15:15) | `data/stream_test_20261027.db` |

# NFCE Desk: a live, read-only trading-desk screen (27 Oct 2026, ~16:00, after the close)
**Test counts:** engine 318, bridge 237 (+3). The bridge itself is unchanged; frozen files all match.

| Change | Evidence / test |
|---|---|
| **`nfce_bridge/ops/desk.py` + `desk.html`:** a separate process (port 8001; `PYTHONPATH=. .venv/bin/python ops/desk.py`) that reads `nfce.db` and `gs.db` through SQLite read-only URIs and the bridge's `/health`. It never writes, orders or blocks. **Panels:** status pills (bridge, poll age, token, power, GS); the six accounts with today's P&L and intraday equity curves; **limit utilisation** with traffic lights (daily loss vs cap, open vs max, premium deployed vs cap, give-back armed or halted, loss streak vs the 3-loss pause); **P&L attribution by book**; signal blotter; **fill blotter with fees (TCA)**; GS by branch; data-feed ages and engines; the research scorecard (`evidence/scorecard.json`); message audit in and out. Refresh every 5 s. `--day YYYY-MM-DD` replays a past day | `tests/test_desk.py` (3): day P&L, limits, curve, books split by leg and day, read-only (a write raises). Checked on the real 26 and 27 Oct data: every figure matches the day logs |

# NFCE-X phase 1 (feature factory, live features) + phase 2 first model; three locked tests (27 Oct 2026, 14:30–15:45; research only, nothing live changed)
**Test counts:** engine 318 (+12), bridge 234. `nfce check`: frozen files all match. GS-SIP-1 verifies FROZEN on a second thread. No new Python packages.

| Change | Evidence / test |
|---|---|
| **`nfce_engine/nfx/features.py`:** 120 point-in-time factors per stock and 3-minute bar (momentum ×8 horizons, volatility, trend incl. MACD/ADX/Aroon/Supertrend/Ichimoku, oscillators incl. RSI/Stoch/CCI/MFI/CMO/Ultimate, time-of-day RVOL/OBV/CMF/VWAP, session/opening range/gap/Donchian, **23 candlestick patterns**, structure, daily). Plus cross-sectional ranks, breadth, VIX and results-calendar events: **140**. `labels()` / `exec_labels()` are future returns, kept apart | `tests/test_nfx_features.py` (7): every factor equal when the future is cut off (verified to catch a planted leak); families; labels; opening range; cross-section; VIX/events |
| **`nfx/live_features.py`:** options (ATM IV from the next non-expiring contract, 25-delta skew, PCR, IV change), 5-level book (L1 and distance-weighted L2–5 imbalance, spread, depth), news (minutes since filing, results, market hours). Real-data checks found two bugs: naive recorder times, and 0DTE IV (33% vs 15%). Both fixed | `tests/test_nfx_live_features.py` (5) |
| **`tools/nfx_build.py`:** feature store `~/Downloads/nfce_data/nfx_features/` (213 stocks, 15-minute decision bars, 3.2 GB, 11.5 min); `--add-exec-labels` | `_meta.json` |
| **`tools/nfx_model.py`:** locked M1 / M1-A1 trainer. Walk-forward, embargo, and one-look validation/final enforced in code | `evidence/nfx_model_protocol.md`, `nfx_model_amendment_1.md` + results: **bounce artifact; with an executable entry 2 of 3 folds negative; 2025 not looked at** |
| **`tools/reversed_signals.py`** | **FAIL:** reversed −0.374R vs −0.270R as given (`evidence/reversed_signals_result.md`) |
| **`tools/ovr_reversal.py`** (OVR-1, Gemini strategy 3) | **FAIL:** −14.4 bp net (`evidence/ovr_reversal_result.md`) |
| **Plan:** `UPGRADE_PLAN_NFCE_X.md` (phases 1–5). Explainer: `~/Downloads/NFCE_SYSTEM_EXPLAINER_FOR_GPT.md`; research prompt `docs/RESEARCH_PROMPT_2026-10-27.md` | — |
| **Found live (closing auction, from 3 Aug 2026):** cash quotes freeze at 15:15; the NIFTY spot froze at 22,760.75 while options traded (22750 CE 203 → 211). The OVN v2 15:20 entry must use the put-call-parity forward (amendment before `score2`). GS exited at 15:15:06 on the last continuous quote | `LIVE_DAY_2026-10-27.md` |

# GS live fix: the store works across threads; GS-SIP-1 re-frozen, counted from 28 Oct (27 Oct 2026, ~09:05, before the open)
**Test counts:** engine 306 (+1), bridge 234.

| Change | Evidence / test |
|---|---|
| `gs/store.py`: `check_same_thread=False`. GS is built on the bridge thread and stepped on the gs-engine thread; at 09:00 every call failed with ProgrammingError, so GS sat the day out | `test_store_made_on_one_thread_works_on_another` |
| GS-SIP-1 re-frozen (manifest `ce4f89c97fc2`); counted from 28 Oct (the tool refuses today's date); 27 Oct is uncounted. Protocol text unchanged | REGISTRY note "GS-SIP-1 re-freeze" |

# GS-SIP-1 registered: history test, freeze, live freeze check (26 Oct 2026, evening; counts from 27 Oct; GS still needs GS=on)
**Test counts:** engine 305 (+11), bridge 234 (+2). `nfce check`: frozen files all match. The bridge was not restarted.

| Change | Evidence / test |
|---|---|
| **History test of GS-SIP-1 as designed** (owner: "count GS … run a random test … on all the data"), pre-declared and hashed first (`gs_sip_1_development_protocol.md`, 16:48). 2022–26, 213 stocks, 3-minute bars, measured time-of-day spreads, ₹1 L tickets: **it lost money after costs.** Market entries −11.6 bp per trade, **−3.7 bp/day** of ₹5 L (95% CI −5.8 … −1.4); strict passive −9.4 bp per trade, **−2.0 bp/day** (−3.8 … −0.2); adverse stress −18.9 bp/day. Gross +4.6 / +6.9 bp per trade vs ~16 bp of costs (median ticket ₹53 k: the fixed ₹40 brokerage alone ≈ 7.6 bp). Random 250 sessions of 2022–24 (seed 20261026) reported too. Development data only | `evidence/gs_sip_1_development.md`; `tools/gs_sip_hist.py`; `tests/test_gs_sip_hist.py` (8) |
| **Improvements:** 3 pre-declared single changes (stop 1.0 ATR, RVOL ≥ 2, window to 10:30), selected on 2022–24 only: **none beat the design under both market and strict passive fills, so the design is kept** (no 2025–26 check needed) | same |
| **Live recorded days** (exploratory replay with the real 14-session history from `hist3m_recent`): 22 Oct no trades (quotes from 11:45); 23 Oct 19 selected, P strict 2 fills −₹67, M 4 fills −₹3,295; 26 Oct (quarter size, VIX +20.2%) P strict 2 fills −₹117, M 6 fills −₹986. Parity replay = adapter on all days | `evidence/gs_sip_1_development.md`, `evidence/gs_sip_replay_exploratory.md`; `ops/pull3m_recent.py` (new, read-only) |
| **Fixed before the freeze:** brokerage is per executed order (later parts of a partly filled passive order paid ₹20 again); the RBI/Budget event block (blueprint section 7) added to the live engine as in the history test | `test_partial_fills_of_one_order_pay_brokerage_once`, `test_rbi_window_and_budget_day_block_entries` |
| **GS-SIP-1 REGISTERED** (16:59): protocol `56661051…4fa1`, manifest `216728d1…1e50` (`evidence/gs_sip_1_manifest.json`, frozen in `data/gs.db`); start 27 Oct 2026; pilot 60 sessions to ~late Jan 2027 | REGISTRY row + note |
| **`bridge/gs_live.py`: runs only the frozen rules.** Each morning it rebuilds the manifest from disk; any difference (code, protocol, fees, dependencies, calendar) and GS sits the day out, shown in `/gs`. Intents carry the protocol SHA. A calendar extension (NSE 2027 holidays, due in December) is the only allowed change, recorded with `register_calendar_extension`; `test_sessions_to_2026_never_change` pins every existing session | `tests/test_gs_live.py` (+2), `tests/test_gs_calendar.py` (+1) |

# v3.7 GS wiring: the GS research engine in the bridge, OFF by default (26 Oct 2026, after the close; not live until the main session reviews it and sets GS=on)
**Test counts:** engine 294, bridge 232 (+6). `nfce check`: frozen files all match REGISTRY.md (v3.7 GS amendment: new hashes for `service.py`, `config.py`). The bridge was not restarted.

| Change | Evidence / test |
|---|---|
| **`bridge/gs_live.py` (new):** with `GS=on` (and `STOCK_ENGINE=on`) the GS-SIP-1 book runs on its own 2 s daemon thread, fed from the 3-minute stock engine's universe, 30-day 3m history and live 1-minute candles, plus ONE batched 5-level quote request for the ≤ 20 selected stocks (every 10 s from 09:21 to 11:33, every 3 s while a decision or order is pending, then only for open positions: ~180 requests per 30 min in the morning). A mid-session restart sits the day out by rule | `tests/test_gs_live.py` (6): off by default; a full morning (select → trigger → passive and marketable fills → 15:15 exit → close, written to `data/gs.db`); request cadence; failures (HTTP 429, an engine error, a glue error) never reach the bridge tick; `/toggle gs off`; late start |
| `bridge/config.py`: `GS` (default **off**), `GS_DB` (default `data/gs.db`). `bridge/service.py`: creates `GSLive` only when on, inside a try; starts its thread from `tick` inside `_safe`; `/health` shows a GS line (informational, never "unhealthy") | REGISTRY v3.7 GS amendment |
| `bridge/bot.py`: read-only admin `/gs` (books, opportunities, fills, P&L, labelled "not yet evidence"; GS-SIP-1 is DESIGN) and `/toggle gs on|off` | `test_gs_is_off_by_default`, `test_a_morning_…` |
| GS never touches the six accounts, nfce.db, the R1–R6 books or any order path; an exception inside GS disables it for the day (fail-closed) | `nfce_engine/tests/test_gs_adapter.py` (only `gs_live.py` imports the adapter) |

# v3.7: give-back stop (DG) in all six accounts; muted chats get no replies; surge alerts show the move since the open (26 Oct 2026, after the close; live from 27 Oct)
**Test counts:** bridge 226 (+4), engine 294. No frozen file changed.

| Change | Evidence / test |
|---|---|
| **DG decision: ADOPTED in all six accounts** (the owner left the call to the assistant). `bridge/account.py`: once an account's closed P&L for the day (after costs, partial exits included) reaches +2 × its risk per trade (start-of-day equity × risk %; CONC 5%) and then falls to half of that peak, no new entries that day. Open positions keep their exits. The latch survives a restart, and only the 5L account sends the 🛑 message | `test_give_back_stop_*` (2). Evidence: `evidence/day_rules_result.md` (V0 exits: +1.05R/day 2022–24, +1.55R/day on unseen 2025, both p < 0.0001; with K4 exits +0.018R, so it never hurt). **Live replay 22–26 Oct (per account, closed P&L): DG would have triggered on 0 of 11 account-days, so the difference is 0 and it made no day worse.** The "+₹70,281 at 10:16 on 23 Oct" was six accounts added together, mostly open P&L; no single account reached +2R closed. It is a risk control, not a profit rule. |
| `bridge/telegram.py`: a chat on the mute list gets no direct replies either (before, only broadcasts obeyed /mute and /stop); admins are never muted. `/stop` confirms before it mutes | `test_a_muted_chat_gets_no_direct_replies_either_but_admins_always_do` |
| `bridge/scanner.py`: volume-surge picks add "↕️ x% since the open (y% vs yesterday's close)". 26 Oct: DRREDDY "SELL +1.3%" had gapped up on results and fallen below its open; the rule trades the move since the open (as tested), and the alert now says so | `test_volume_surge_picks_say_the_move_since_the_open_not_only_the_day_change` |

# GS phase 0c: recorder timestamps; GS integration staged, not applied (26 Oct 2026, after the close; nothing live changed)
**Test counts:** engine 294 (+3), bridge 222. Frozen files: all match REGISTRY (preflight check).

| Change | Evidence / test |
|---|---|
| **Recorder timestamps (review A finding 3):** `ops/collect.py` and `ops/collect_chain.py` store, per row, `req_ts` (that request was sent), `resp_ts` (its response received) and `exch_ts` (the quote's exchange `timestamp`; empty for chains, which have none). `ts` keeps its old meaning, so every reader works unchanged; a database started by the old recorder gains the columns. Applied at 15:36, after both recorders had exited; first used at the 27 Oct 09:15 start. `tools/overnight_options.py read_chain2` already reads `req_ts`/`resp_ts` when present | `nfce_engine/tests/test_gs_recorders.py` (3; HTTP stubbed) |
| **GS integration staged** (owner, during the session: "prepare to integrate"): `bridge/gs_live.py` (GS on its own 2 s thread, fed from the stock engine + one batched depth request), `/gs`, `/toggle gs`, `GS`/`GS_DB` settings; **off by default**. Applied only after the main session's own bridge edits, then reviewed by it before any restart | `GS_INTEGRATION_PLAN.md`; staged run: bridge 228 passed (6 new) |
| GS-SIP-1 (still DESIGN): selection waits until 09:21:30 (the bridge sees the 09:18 bar ~15–20 s after 09:21); `tools/gs_manifest.py` also hashes `bridge/gs_live.py` | `tests/test_gs_sip.py` |
| Exploratory replay refreshed on the full 26 Oct quote file: parity OK (replay ×2 = adapter) on 22, 23 and 26 Oct | `evidence/gs_sip_replay_exploratory.md` |

# GS engine phase 4: locked evaluation + registry; GS-SIP-1 protocol (DESIGN) (26 Oct 2026, afternoon; nothing live changed)
**Test counts:** engine 291 (+14), bridge 222.

| Change | Evidence / test |
|---|---|
| `gs/evaluate.py`: stationary block bootstrap (block 5, 50,000 replicates, seed 20261026, null-centred one-sided p and bounds), fixed-block 10/20 hurdles, power N = ceil(1.5 × ((2.734 + 0.842) σ/δ)²) (A's 940 / 691 reproduced), pilot futility (90% upper bound < 0), validation gate, final verdicts PASS/FAIL/INCONCLUSIVE/INFEASIBLE (unresolved exposure that could flip → INCONCLUSIVE) | `tests/test_gs_evaluate.py`: null iid rejects at ≈ nominal, a dependent (AR 0.6) null over-rejects without blocks and not with them, a 0.3 SD effect is found, nulls rarely pass α = 0.003125 |
| `gs/registry.py`: manifests hashed; DESIGN cannot freeze; one record per stage, in order, refused on a second look or after a manifest change; `tools/gs_manifest.py` builds the GS-SIP-1 manifest with current code/dependency/calendar/fee hashes | `tests/test_gs_evaluate.py` |
| **`evidence/gs_sip_1_protocol.md`** (SHA `56776aa5…2017`), **status DESIGN**: the exact rules, scenarios, sizing, stages and verdicts. It starts only after the main session wires the adapter and freezes the manifest. Note: at ₹1 L the fees alone are ≈ 8.3 bp a round trip | — |
| SIP engine: ×1.5-spread figure per opportunity (marketable fills only); worst/best bounds for unresolved positions | `tests/test_gs_sip.py` |
| OVN v2 amendment 1 (14:28, before the first entry): the `stress2` diagnostic no longer crashes at the calendar's start. Result: the open gapped ≥ 1 previous-day ATR14 (the wing) on 3.9% of 1,182 nights 2022–26 | REGISTRY amendment row |

# GS engine phase 3: features, GS-SIP-1, bridge adapter (unwired), replay (26 Oct 2026, afternoon; nothing live changed)
**Test counts:** engine 277 (+20), bridge 222. `nfce_bridge/bridge/gs_adapter.py` is new and **imported by nothing** (a test checks it).

| Change | Evidence / test |
|---|---|
| `gs/features.py`: as-of ATR14 (Wilder, previous sessions only), the 09:15–09:21 window, RVOL (all 14 previous sessions valid), ER20 and book imbalance (diagnostics only), VIX state; any input available after the decision raises | `tests/test_gs_sip.py` |
| `gs/alpha_sip.py`: **GS-SIP-1 exactly as blueprint section 5** — top 20 by RVOL at 09:21 (ranked before breakouts), triggers on bars starting 09:30 and closing by 11:30, passive limit min(boundary, bid)/max(boundary, ask) active after 2 s and expiring after 180 s or 11:33, **branch M** (marketable after the same 2 s), stop 0.5×ATR14 at the next book after the latency, 15:15 exit at the touch, ₹1 L ticket with risk/capacity/section 7 caps; unfilled opportunities score zero and are kept | `tests/test_gs_sip.py` (15) |
| `bridge/gs_adapter.py` (not wired): the same engine methods, its own `data/gs.db`, every call fail-closed (an error disables GS for the day and never reaches the bridge) | `tests/test_gs_adapter.py` (4): live = replay byte for byte, isolation, restart idempotence, no importers |
| `tools/gs_replay.py`: **exploratory** parity/smoke runs on `study_quotes_2026102*.db`. Parity OK on 22, 23 and 26 Oct (two fresh runs = the adapter path). As registered, the rule selects nothing on those days because the recordings miss openings (22 Oct started 11:45; 23 Oct after 09:21, so 26 Oct lacks a 14th window); a labelled "relaxed" smoke mode pushes real books through fills and exits. No P&L there means anything | `evidence/gs_sip_replay_exploratory.md` |
| `gs/execution.PassiveOrder`: incremental limit order (the same object for live and replay); the crossing-on-arrival check uses the market as the order arrives | `tests/test_gs_execution.py` |

# GS engine phase 2: paper execution + shared request budget (26 Oct 2026, afternoon; nothing live changed)
**Test counts:** engine 257 (+20), bridge unchanged. Not wired into anything.

| Change | Evidence / test |
|---|---|
| `gs/execution.py`: 5-level book walk (never past level 5); capacity = notional ≤ 5% of the trailing 5-minute average traded value per minute and ≤ 3 bp impact beyond the touch (partial size, or skip); marketable fills only after the latency, on a valid uncrossed book within the wait limit; passive limits with three scenarios (touch = illustration; strict = a later quote through the limit by ≥ 1 tick, filled AT the limit, ≤ 10% of the visible size per quote; adverse = strict minus the best 25% of fills and −2 bp); a limit that crosses on arrival is marketable; markouts at 10 s / 1 min / 5 min | `tests/test_gs_execution.py` |
| Multi-leg state machine: wings first, then shorts; a failed short sells the wings back at executable quotes (legging loss kept) or leaves a RESIDUAL; exits close shorts before wings; missing quotes leave legs open, never a stale mark | `tests/test_gs_execution.py` |
| `gs/budget.py`: one sliding-window bucket in SQLite, shared by every process (≤ 1,600 / 30 min, ≤ 4 / s), priority ceilings so exits and health always have the last tokens, HTTP 429 freezes new entries with jittered back-off | 3 tests, one with 3 real processes |

# GS engine phase 1: core types, calendar, store, fees, ledger, risk (26 Oct 2026, afternoon; nothing live changed)
**Test counts:** engine 237 (+41 in phase 1), bridge unchanged. New package `nfce_engine/gs/`; no bridge file touched; nothing imports it yet.

| Change | Evidence / test |
|---|---|
| `gs/types.py`: immutable Event / Leg / Intent / Approval / ExecutionEvent / FeatureSnapshot / Verdict; timezone-aware times; content-hash IDs, so a replay gives the same intent and fill IDs | `tests/test_gs_store.py` |
| `gs/calendar.py`: NSE sessions 2022–26 (holidays from the data to 21 Oct; the published list after), Muhurat/DR sessions marked special, weekly/monthly expiries moved back over holidays, RBI/Budget event dates; a date outside the snapshot raises | `tests/test_gs_calendar.py` |
| `gs/instruments.py`: lot/tick/strike step by effective date (an unknown lot raises); limit rounding against aggressiveness | `tests/test_gs_calendar.py` |
| `gs/store.py`: append-only SQLite (WAL; UPDATE/DELETE abort), idempotent inserts, replay in availability order, one verdict per protocol | `tests/test_gs_store.py` |
| `gs/costs.py`: per-fill fees by fill date, wrapping the frozen `nfce/costs.py` unchanged (fill fees add up to the frozen round trips to the paisa); cash equity at ₹20/order. **At a ₹1 L ticket the round-trip fees alone are ≈ 8.3 bp** (₹40 brokerage = 4 bp) | `tests/test_gs_ledger.py` |
| `gs/ledger.py`: signed legs, cash accounting, reserves, unresolved positions (bounds only, never a stale mark); cash long, cash short and an iron fly at max loss reconcile to the paisa | `tests/test_gs_ledger.py` |
| `gs/risk.py`: section 7 regime map, cash sizing (0.25% risk; stop + 0.25 ATR + friction + fees), portfolio caps (gross/net/stock/sector/4 open/stress/cluster), option caps (budget, overnight, shared short-vol), DG latch per book, day-loss latch (marks + reserves), drawdown pause until review; pending intents count at full size and stale marks block entries | `tests/test_gs_risk.py` |

# GS engine phase 0: review A's findings, OVN v2 (26 Oct 2026, afternoon; nothing live changed)
**Test counts:** engine 196 (+18), bridge 222 (recorder timestamps: see 0c below). Records: `evidence/gs_phase0_amendments.md`, `evidence/overnight_options_v2_protocol.md`; REGISTRY rows appended.

| Change | Evidence / test |
|---|---|
| **Overnight test v2 = GS-OVN-1** (hashed 13:54, before the 15:20 entry): next session from the exchange calendar; no LTP marks (open legs leave the structure unresolved, with bounds); entry fees from the entry fills and a separate stress-grid exit-fee reserve; wings 1×previous-day ATR14 rounded up to the strike step; ₹10 L book, 0.5% budget; shorts closed before wings; pilot 60 / validation 60 / final N. v1 superseded before its first entry; its code path is unchanged | `tools/overnight_options.py score2`; `tests/test_overnight_v2.py` (13) |
| **A's findings checked:** 1, 3–9 and 11 real; 2 real but immaterial (0 tradable regular sessions dropped of 246,167 stock-days); 10 a caution | `evidence/gs_phase0_amendments.md` |
| **H2 re-scored with the open-entry cost** (67% of its entries were before 09:30): net −2.6 → **−3.5 bp/trade** (−0.018 → −0.025R); H1/H3 also slightly worse; all still FAIL the development gate. Labelled a correction | `study2_result.md` (appended "Correction"); `tools/study2_rescore.py`; `test_orb_entries_before_0930_pay_the_open_slippage` |
| `news_reaction`: R1 enters on a quote strictly after the one that completed AR5; NIFTY quote ages bounded. `range_vs_implied`: exchange holidays excluded. Both before their first judged session (27 Oct); flags reproduce the old behaviour | 3 new tests |

# Research: PBO + three forward tests registered (26 Oct 2026, midday; nothing live changed)
**Test counts:** engine 178 (+22), bridge 222, all passing. No file in `nfce_bridge/` was touched; the chain, news, quote and nfce databases are read read-only.

| Change | Evidence / test |
|---|---|
| **PBO by CSCV** (Bailey et al.) in `tools/study.py` (`pbo_cscv`), reported in both study engines. v1: PBO 0.00 over 2,040 rules (12,870 splits); v2: 0.00 over 8. **Read carefully:** PBO is relative to the other trials. Most rules lose steadily, so the near-zero gap-fade family keeps ranking first; the tests against zero (SPA, Holm, the forward stages) all fail | `study_engine_result.md`, `study2_result.md`; 3 tests in `test_study.py` |
| **Overnight defined-risk NIFTY option selling** (research note test 2): an ATM iron fly (primary) and a 1-SD iron condor, entered 15:20 from the recorded chain, exited at 09:16 the next day, two skip filters (ATM IV up ≥ 5% since 11:00; the range model's forecast in its top 20%). Judged at 40 entered sessions. Stress check (2022–26): 5.6% of nights move more than 1 VIX-implied overnight SD, 0.7% more than 2 SD; worst 2025-04-04 → 07 (−5.0%, −5.8 SD) | `evidence/overnight_options_protocol.md` (hashed 11:35, before the first entry); `tools/overnight_options.py`; `tests/test_overnight_options.py` (10) |
| **Range model vs the option-implied move** (test 3), a measurement with no trades: the ATM straddle converted into an expected 1-hour range, vs M1/HAR/ENS; claims C1 (an intraday variance premium), C2 (the model forecasts better), C3 (the disagreement predicts realized/implied). From 27 Oct; judged at ≥ 20 sessions | `evidence/range_vs_implied_protocol.md` (hashed ~11:40); `tools/range_vs_implied.py`; `tests/test_range_vs_implied.py` (4) |
| **News reaction** (test 5): F&O stock abnormal returns at +5/15/30/60 min after in-hours NSE announcements, by group; rule R1 (follow a ≥ 0.40% 5-minute move, exit at +60 min) with real quotes and fees. From 27 Oct; judged at ≥ 100 trades and ≥ 30 sessions | `evidence/news_reaction_protocol.md` (hashed 11:41); `tools/news_reaction.py`; `tests/test_news_reaction.py` (5) |

# Research: study engine v2 (26 Oct 2026, during the session; nothing live changed)
**Test counts:** engine 156 (108 + 36 + 12 new), bridge 222, all passing. No file in `nfce_bridge/` was touched.

| Change | Evidence / test |
|---|---|
| **Study engine v2** (owner: "search the web, fix the mistakes like volume to volatility, refer to news, test again, as if a bank used it"). `tools/study2.py` tests 8 hypotheses from published research and the v1 lead, with the published parameters: stocks-in-play ORB (Zarattini-Barbon-Aziz) with two stops and on results days; index last-half-hour momentum (Gao et al.; Baltussen et al.); stock end-of-day reversal; the v1 gap fade, exactly and in ATR units. What it fixes: relative volume selects the top 20 in play across the market; thresholds and stops are in ATR; asymmetric hold-to-close exits; order-book costs | `evidence/study2_protocol.md` (hashed first), `study2_result.md`, `study2_trades_summary.csv`; `tests/test_study2.py` (12; the top-20 test caught a look-ahead in the first draft) |
| **Result: 0 of 8 pass.** 7 fail the 2022–24 gate. H7 made +0.121R/trade in the one-shot 2025–26 final, but its days lost (p(day) 0.98): the profit is 2–4 market-wide panic gap-downs, so FAIL. **Key finding:** the stocks-in-play breakout has a real gross edge (+10–13 bp, every year) about equal to the market-order cost (12.6 bp). The bottleneck is execution, not indicators | `study2_result.md` |
| **Costs re-measured from the order books** (22–23 Oct depth): cash-equity intraday ₹3 L ≈ 3.7 bp per side and futures ≈ 4.6–4.9 bp (v1 assumed 2). Since Budget 2026, futures STT is 0.05% vs 0.025% for cash intraday, so cash equity is the cheaper venue for stock trades up to ~₹3 L | `study2.py costcheck`; `study2_result.md` |
| **Plan** (not switched on): a registered paper account trading the stocks-in-play breakout with limit orders (needs bridge code: main session / owner, after the close); depth-aware sizing; a forward LLM-news filter on official NSE announcements; long-volatility options on the range model | `study2_result.md` ("The plan") |

# Research: study engine (26 Oct 2026, during the session; nothing live changed)
**Test counts:** engine 144 (108 + 36 new), bridge 222, all passing. No file in `nfce_bridge/` was touched.

| Change | Evidence / test |
|---|---|
| **Study engine** (owner: "test all the tricks and indicators on every bit of data"). `tools/study.py` runs 2,232 intraday rules in one command: 16 indicators (RSI both reads, MACD, Bollinger break/fade, Supertrend, VWAP cross/stretch, ORB 15/30, EMA crosses, ADX/DI, relative volume, gap follow/fade, prior-day high/low, NR7/inside-day ORB) × settings × side × K1/K2/K4 exits × all-day/morning × VIX regime. It runs on 213 F&O stocks (3m) and NIFTY/BANKNIFTY (5m), at the house cost model, train 2022–23 → validation 2024 → a one-shot final 2025–26, with White's reality check, Hansen SPA, the deflated Sharpe and Holm over all rules tried. Adding an indicator takes one function and one registry line | `evidence/study_engine_protocol.md` (hashed first), `study_engine_result.md`, `study_engine_rules.csv`; `tests/test_study.py` (36: look-ahead for every indicator, walk and cost parity with the existing code, statistics) |
| **Result: 0 of 2,232 rules survive.** Before costs the indicators have no edge (median gross −0.005R, 44% gross-positive). 23 train candidates all failed 2024 (Holm 1.000); the train SPA p is 0.12 and the reality check p 0.57. The final was not run. The weak lead "fade a ≥ 2% gap" is not significant and close to zero at real spreads. Nothing is switched on | `study_engine_result.md` |
| **Cost-model check:** live stock-futures half-spreads are a median 4.6 bp against the model's 2.0 bp per side (NIFTY 2.55 pts vs 0.4). The stock studies are optimistic by about 0.07R/trade at 1R exits. The frozen friction is not changed; it is a proposal for after more quote days | `study_engine_result.md` (cost check) |
| **News + LLM** (owner's question): it cannot be backtested honestly (no point-in-time news archive; an LLM knows the outcomes). Only a forward, registered paper test can measure it | `study_engine_result.md` |

# v3.6 (23 Oct 2026, evening, after the third live session)
**Test counts:** engine 108, bridge 222, all passing. The day's record is in `LIVE_DAY_2026-10-23.md`.

| Change | Evidence / test |
|---|---|
| **True breakeven (live bug, 23 Oct).** After T1 a runner's "breakeven" stop was on the UNDERLYING's entry, but the accounts hold OPTIONS: HINDZINC/PFC/SENSEX runners exited at "breakeven" for −₹4,148 / −₹3,430 / −₹907. Now a runner exits as soon as the option's bid falls to the premium paid plus fees. A correction of the rule's meaning, in all accounts. It can also cut some runners short (not measurable without option history; watched live) | `test_after_t1_a_runner_never_turns_into_a_loss_on_the_option` (fails on v3.5) |
| **`nfce stop` / `status` could not see the bridge:** `pgrep -f "-m bridge.start"` reads the pattern as an option. The supervisor's process check had the same bug (it would always say "no process"). One safe pattern `[-]m bridge[.]start` | `test_the_process_pattern_finds_a_real_bridge_process` (a real process) |
| **📰 Results flag** (admin: "consider news, results"). NSE board-meeting calendar 2022–26 (46,346 meetings; 211/213 F&O stocks). **Tested first:** signals in results windows did NOT do worse (V0 −0.170 vs −0.275R; K4 +0.010 vs −0.036R), so no skip rule. Stock and scanner alerts show "results today / yesterday / next trading day"; one NSE request a day, in the background; never blocks an alert | `evidence/results_days_protocol.md` (hashed first), `results_days_result.md`; `bridge/events.py`; `tests/test_results_calendar.py`; `ops/pull_results_calendar.py` |
| **Study: profit lock** (why the +₹70,281 morning became −₹3,080). P1 breakeven lock −0.050R and P2 half-profit trail −0.063R, both **worse** than no lock (K4 −0.034R). **FAILED, not adopted**: locks cut the runners where the small edge lives | `evidence/profit_lock_protocol.md` (hashed first), `profit_lock_result.md`; `tools/profit_lock.py`; `stock3m_research.trades(walkers=...)` |
| **Scanner SELL-only** (`SCANNER_MODE=sell`; the owner: "do what's best"). Buying the top gainers lost on all 3 live days (−₹71,410 on 23 Oct) and in every 2022–24 row. The losers are still paper-traded as SELL picks; gainers become watch-only lines. The book is outside the accounts | `test_sell_only_scanner_trades_the_losers_and_only_watches_the_gainers` |
| **Study: K4 in results windows** (confirmation of the lead): 2025 −0.021R (CI includes 0): **FAILED**, lead closed | `evidence/results_k4_protocol.md` (hashed first), `results_days_result.md` |
| **REGISTRY correction:** two rows of the superseded 18 Oct table (paper.py, config.py) had been overwritten by earlier whole-file hash replacements; restored from older copies | `REGISTRY.md` (correction note) |
| **Study (25 Oct): the opening gap / GIFT Nifty.** GIFT Nifty is not in the Upstox feed; its main value is an earlier read of NIFTY's gap, which the engine knows exactly by 09:30. Following the gap −0.140%/day (2019–24); as a filter for stock signals −0.257R (V0) / −0.017R (K4): **all FAILED**. GIFT Nifty is not added | `evidence/gap_protocol.md` (hashed first), `gap_result.md`; `tools/gap_study.py` |
| **Study (25 Oct): day-level profit booking.** DG (stop new trades after a +2R day gives back half) and DT (+3R target) cut losses with the live exits on 2022–24 AND 2025 (DG +1.55R/day in 2025), but the days stay negative: **risk control only**. Decision deferred to Monday (owner: the assistant decides then) | `evidence/day_rules_protocol.md` (hashed first), `day_rules_result.md`; `tools/day_rules.py`; exit_time recorded in `stock3m_research` |
| **Study (25 Oct): three profit-rule candidates** that trade rarely: market-neutral 12-1 momentum (XM, closest: +0.52%/month but p 0.066: FAIL), 5-day reversal (XR: FAIL), NIFTY overnight (ON: passed 2019–24, then −10.6% in 2025: FAIL) | `evidence/xs_protocol.md` (hashed first), `xs_result.md`; `tools/xs.py` |
| **Study: XM on the untouched 2006–16 sample** (owner's go-ahead; rule unchanged): −0.20%/month, gross +0.003%: **FAILED**, XM closed. **Bug found and fixed:** the daily loader's calendar included NIFTY-only special sessions, so stocks lost their 60-day vol for about 3 months after each. Fixed, and the 25 Oct tests re-run: every verdict unchanged | `evidence/xm_old_protocol.md` (hashed before the download), `xm_old_result.md`; `tools/tsmom.py` (load) |
| Minute quotes of 23 Oct (157,990 rows) | `data/study_quotes_20261023.db` |

# v3.5 (22 Oct 2026, evening, after the second live session)
**Test counts:** engine 108, bridge 216, all passing. The day's full record is in `LIVE_DAY_2026-10-22.md`.

| Change | Evidence / test |
|---|---|
| **Bug (live):** `/account` valued open positions at their entry price, not the live bid (12:36 showed ₹4,93,850 while the minute curve had ₹4,92,120). The report now uses the latest quotes | `test_report_marks_open_positions_at_the_live_bid_not_the_entry` (fails on v3.4) |
| **Five strategy paper accounts** (`ACCOUNTS=NAME:capital:strategy`; the admin asked for 5 accounts, and equal capital with different handling was offered as the better design): 5L base, CONC concentrated (5%, ≤ 3 a day), WIDE (2× stop), CONF (enter after 0.5R confirmation), CLUS (≤ 2 same-direction entries per 30 min + 30-min time stop). The extra four are quiet; `/account` and the daily report show them side by side; `/set` changes only the base accounts | `evidence/strategy_accounts_protocol.md` (hashed before the open); 7 tests in `test_account.py` / `test_bot.py`; dress rehearsal on a copy of the live DB |
| **Bot:** with the assistant relay on, an admin message longer than 6 words goes to the assistant instead of a keyword command ("check was this trade a success" had become `/today`) | `test_an_admins_longer_message_goes_to_the_assistant_not_a_keyword_command` (fails on v3.4) |
| **`nfce` control panel** (`nfce_bridge/nfce` → `bridge/panel.py`, installed as `~/.local/bin/nfce`; standard library only, so it runs on a new Mac before setup).
  - **Menu:** with no arguments, an interactive menu.
  - **Commands:** `status`, `start` (detached, with preflight and a sign-in prompt), `stop` (sets the maintenance switch in market hours), `restart`, `login` (the owner signs in), `check [--live]`, `fix`, `logs`, `messages`, `accounts`, `report`, `test`, `study`, `backup`, `supervisor on|off|status`, `setup` (venv + pinned packages, `.env` keys typed hidden, the command, optional supervisor, tests, checks), `env [set KEY]` (masked).
  - **`fix`:** repairs what is safe: environment, missing keys, DB restore from a backup (asks first), leftover maintenance switch, stuck bridge, expired token (sign-in), log rotation. It only reports ledger mismatches, battery, disk and port conflicts. | `tests/test_panel.py` (5); live runs of status, fix, env, help |
| **No background process by default** (owner, 22 Oct): the supervisor/offline responder is opt-in (`nfce supervisor on` installs a launchd agent; `off` removes it). The launchd agent installed earlier this evening was removed at the owner's request | `nfce supervisor status` |
| **Self-healing supervisor** (inside the offline responder; 22 Oct: the bridge died at 09:49 and nothing noticed for 30 min).
  - **When it acts:** weekdays 09:15–15:15, and only for a bridge that already ran that day (the morning start stays the owner's).
  - **Dead bridge:** after 60 s with no bridge process, it restarts it detached; at most 3 times a day, then "needs a person".
  - **Hung bridge** (market loop silent > 5 min): it stops it and `start.sh` restarts it.
  - **Messages:** the admin is told every time.
  - **Off switch:** `touch ~/.nfce_maintenance` makes it stand down. | `tests/test_offline_bot.py` (5 supervisor tests) |
| **Preflight self-check** `python -m bridge.preflight` (offline, sends nothing).
  - **Checks:** .env keys; DB integrity; every account ledger reconciles to its cash (₹1); no positions left open after the close; frozen-file hashes vs the CURRENT REGISTRY table; the range models load; disk; the supervisor is running; power; token.
  - **Where it runs:** at every `start.sh`; its problems go into the 09:05 morning brief. | `tests/test_preflight.py`, `test_the_morning_brief_lists_preflight_problems`; first live run: 10/11 ok, only "on battery" |
| **Test isolation:** bot tests never read this Mac's battery or the live `.env` (both leaked into tests on 22 Oct and were caught) | full suite in any order |
| **Offline responder** (admin, 16:39: "a better bot that even responds when the system is offline"): `bridge/offline_bot.py`.
  - **Answers while the bridge is stopped:** `/status`, `/account`, `/today`, `/risk`, `/about`, `/ledger` (admin), `/meme`, `/help`.
  - **Other messages:** saved for the assistant and the admin.
  - **Polling:** only while `/health` does not answer; it shares the bridge's update offset, so nothing is answered twice.
  - **Safety:** read-only (never trades or changes settings). | `tests/test_offline_bot.py` (3); dry run on the real database |
| **Bot:** `/risk` and `/meme` while running. The alerts themselves stay strictly professional | `test_risk_and_meme_commands_while_running` |
| **Risk view (the one Aladdin-style idea that fits: see the whole book's risk at once):** `/account` shows SELL/BUY counts and the loss if every premium stop is hit; a buy that makes 3+ positions all one direction carries a warning (22 Oct 12:12: four SELLs were one market bet) | `test_risk_view_shows_direction_and_the_loss_if_every_stop_is_hit` |
| **Battery watch (live 22 Oct: on battery all day, nobody warned by the system):** the watchdog tells the admin once a day when the Mac is on battery, and again at ≤ 25%. Tests never read the real battery | `test_watchdog_warns_the_admin_when_the_mac_runs_on_battery`, `test_power_status_reads_pmset` |
| **Dress rehearsal for 23 Oct:** one engine signal through the real Bridge into all five accounts, through the stop; only 5L's messages are sent | `test_one_engine_signal_reaches_all_five_strategy_accounts_and_only_5L_talks` |
| **Operator scripts** in `nfce_bridge/ops/` (reply, watch, collect, pull1m, pull3m_fo, day_study); replies sent with `ops/reply.py` are now logged in `sent_messages` (the 22 Oct replies were not) | `ops/README.md` |
| **Scanner back in trade mode** (`SCANNER_MODE=trade`, owner 22 Oct 11:15): picks are paper-traded in the `scanner` book, outside every account | live 13:15 scan: 13 trades |
| **Study: same-direction cap on 2022–24** (4,460 stock 3m trades): worst day −12.15 → −10.13R (17%), max drawdown 1,507 → 1,305R (13%): **FAILED** the 25% bar; per trade −0.338 → −0.331R | `evidence/cap_replay_protocol.md` (hashed first), `cap_replay_result.md`; `tools/cap_replay.py` |
| **Study: scanner SELL side only** (10,708 trades, 2022–24): −0.065R per trade: **FAILED**; the 13:15 SELL scan is the worst row (−0.101R) | `evidence/leads_2day_protocol.md` (hashed first), `leads_2day_result.md`; `tools/leads_2day.py` |
| **Studies on 210 F&O stocks, 2022–24 (16,598 stock 3m trades; 159 stocks never used before), all registered first: morning-only −0.224R, index-aligned −0.260R, aligned+morning −0.217R, meta-labeling 2025 −0.327R (AUC 0.511): all FAILED.** The gross edge is about +0.05R and costs take about 0.3R; no filter closes that gap | `evidence/leads_2day_result.md`, `best_practice_tests_result.md`, `best_practices_review.md`; `tools/leads_2day.py`, `tools/meta_label.py` |
| **Study: wider stops** (K2/K3/K4, one engine run; 16,598 trades): net −0.270 → −0.107 → −0.054 → −0.034R; cost share 29% → 7%. **All FAILED** (never positive).
  - **Why:** at 4×, 71% of trades ride to 15:15; the entries' drift is smaller than the futures round trip.
  - **Action:** a sixth account **WID4** (4× exits through options, risk at most the premium), registered as amendment 1 before any trade. | `evidence/wide_stop_protocol.md`, `wide_stop_result.md`, `strategy_accounts_amendment_1.md`; `tools/wide_stop.py`; `test_wide4_*` |
| **Study: weekly time-series momentum on 213 F&O stock futures** (daily data 2016–26, measured costs 8 bp/side). TS250 passed train 2019–24 (Sharpe 1.18) but **FAILED** the one-look 2025 validation (−5.2%; the long-only benchmark +4.8%); TS60/TS120 failed train. The train pass was the bull market (the shorts lost even then) | `evidence/tsmom_protocol.md` (hashed first), `tsmom_result.md`; `tools/tsmom.py`; `ops/pull_daily.py` |
| **Alerts quote the new track record** (16,598 trades, −0.27R; 4× stops −0.03R) instead of the old 4,460-trade figure | — |
| **Data:** 1-minute candles for 21–22 Oct (431 instruments); minute quotes with depth for 427 instruments (11:45–15:30); 3m history 2022–26 for all F&O stocks (in progress) | `nfce_bridge/data/study_1m/`, `study_quotes_20261022.db`, `~/Downloads/nfce_data/hist3m_fo` |

# v3.4 (21 Oct 2026, late evening): a bot that runs without an assistant; account loss-avoidance rules
**Test counts:** engine 108, bridge 185, all passing.

| Change | Evidence / test |
|---|---|
| **Roles** (`TELEGRAM_ADMIN_CHAT_IDS`): the admin (the "S" chat) controls everything; users get signals, reports and read-only commands; unknown chats get nothing and become access requests to the admin (`/adduser <id>`). Broadcasts reach every known chat that has not muted itself; admins always get them | `tests/test_bot.py` |
| **Admin commands:** `/pause` `/resume` (books and accounts), `/close <n\|all>` and `/reset` and `/restart` (each with a confirmation code), `/set risk\|losslimit\|maxopen\|costgate\|deploy\|stockrisk` (bounded, saved across restarts), `/toggle index\|stocks\|scanner`, `/users` `/adduser` `/removeuser` `/mute` `/unmute`, `/broadcast`, `/notes`, `/errors`, `/config`, `/report`, `/export`, `/backup` | `test_bot.py` |
| **Upstox sign-in from the phone:** `/login` sends the Upstox link; after signing in, the admin pastes the (unloadable) 127.0.0.1 address with `/code`; the bridge swaps the single-use code for the day's token. State-checked | `test_phone_login_*` |
| **User commands:** `/today`, `/open` (live P&L), `/watch` (latest watchlist), `/pnl`, `/explain`, `/about` (what is and is not proven), `/ask` (to the admin), `/stop` `/start`, `/myid`; plain-English questions ("profit?", "open positions", "gainers", "is it working?") are answered; longer statements stay notes and a user's note is forwarded to the admin | `test_plain_english_*` |
| **Unattended jobs:** token watch from 08:00 (admin reminder with `/login`), 09:05 morning brief, health watchdog (alert after 3 minutes, all-clear on recovery), error-burst alert, 15:35 ledger to the admin + database backup (last 10 kept) | `test_watchdog_*`, `test_token_watch_*`, `test_errors_*` |
| **start.sh:** keeps the Mac awake itself (`caffeinate -w`), restarts the bridge after a crash or `/restart` (gives up after 5 quick failures); a missed Upstox login no longer stops the start (sign in later with `/login`) | manual |
| **Account loss-avoidance rules** (chosen before any result; risk controls, not a measured edge): cost gate (spread + fees ≤ 25% of the risk), one position per underlying, ≤ 60% of equity in premium, 30-minute pause after 3 losses in a row, premium stop when the underlying's quote is stale (SENSEX), hard stop at 1.5× the planned premium risk | `tests/test_account.py` (12); replay of the 36 stock legs of 21 Oct: 9 skipped by the cost gate |
| **Study: stock signals on 15-minute bars** (4,056 trades, 2022–24): −0.18R per trade after costs; the wider stops halve the cost share (17%) but the edge before costs disappears (+0.001R). FAILED; nothing changes live | `evidence/stock15m_protocol.md` (hashed first), `stock15m_result.md` |
| Telegram: an HTML formatting slip is resent as plain text instead of being lost | — |

# v3.3 (21 Oct 2026, after the first live session)
**Test counts:** engine 108, bridge 171, all passing. The day's full record is in `LIVE_DAY_2026-10-21.md`.

| Change | Evidence / test |
|---|---|
| **Paper account** (`bridge/account.py`): ₹5,00,000 (`ACCOUNTS=5L:500000`); option trades sized to ≤ 1% risk; cash; ≤ 4 open; no entry after 14:45; 3% daily loss limit; exits on the underlying (whole-lot 40/30/30, breakeven, 15:15); exact ledger, minute equity; `/account`, `/ledger`. Real futures margin checked (1 NIFTY lot ₹1.69 L), so the account trades options | `tests/test_account.py` (7): the ledger reconciles to the cash; dress rehearsal |
| **Watchlist scanner** (owner: gainers are to watch, not to buy): no BUY/SELL, no auto trades; signals on watchlist stocks tagged 👀; opening watchlist at 09:21 and 09:30; no duplicates | Live 21 Oct: buying gainers lost −₹31,337, all IT gainers faded; `test_watchlist_*` |
| **Stock 3m signals tested on 2022–24** (4,460 trades): −0.34R per trade after costs, failed even with a cost gate. Information only; the account trades their option legs at ¼ risk as a live experiment | `evidence/stock3m_protocol.md` (hashed first), `stock3m_result.md` |
| **EARLY mode** (first 15 min): zero signals in 4.5 years (the engine's opening range and room checks cannot pass), so its account risk is 0, replaced by the opening watchlist | `early3m_protocol.md`, `stock3m_result.md` |
| Live fixes: readable HTML messages; logged sent messages; `@admin:` instructions; creator chat (`TELEGRAM_EXTRA_CHAT_IDS`, per-thread replies); 3m timeframe for NIFTY/SENSEX; stock 3m engine from the batch 1m feed (validated 38/38 against Upstox 3m); empty-history crash; 1m feed during load; warm-up on any start; retry back-off; spread limit 0.25%; an option leg for every stock signal; faster loading (4 requests/s) | 171 tests; day log |

# v3.1 (20 Oct 2026, evening): the owner's requests (NIFTY/SENSEX options, F&O scanner)
**Test counts:** engine 108, bridge 156 (v3.2: +3 pre-flight timing tests), all passing.

| Change | Evidence / test |
|---|---|
| The bridge's own NFCE signals from live Upstox futures candles (`bridge/live_engine.py`), so no paid TradingView is needed. The engine gained `run(..., open_out=[])` to report a position opened on the last bar: trades are only listed on exit, a gap found by the new live-vs-batch test | `tests/test_live_engine.py`, `test_open_position_at_the_end_is_reported_for_live_use`; real July 2026 replay: 4 signals in 5 sessions, 86 ms per bar |
| SENSEX: BSE instruments file, BSE future, BSE option chain; tick ₹0.05; evidence card labelled "untested on SENSEX" | `test_sensex_futures_come_from_the_bse_file` |
| Option legs: 1-ITM call/put at the nearest expiry after today, ask in / bid out, delta-mapped SL/targets, 5% spread limit; `options` paper book follows the underlying's exit | `test_option_*`, `test_engine_signal_opens_futures_and_option_leg_*` |
| F&O scanner (top gainers / losers / volume surges, 246 F&O stocks, 10:15 / 11:15 / 13:15) with levels, option legs and the `scanner` paper book. **Tested before it was built: all 9 rules lose after costs** | `evidence/scanner_protocol.md` (hashed first), `scanner_result.md`; `test_scanner_*` |
| Setup checker: SENSEX, engine candles, an option leg example, heavyweight keys, F&O universe | `check_setup.feature_checks` |
| Telegram: long messages split, not truncated; free text saved as notes | `test_long_messages_*`, `test_free_text_*` |

# v3.0 (20 Oct 2026): independent review round 3, range benchmark, R6 (final package)
**Test counts:** engine 107, bridge 142, all passing. 34 new regression tests from the reviewer's own failure scenarios; 33 fail on v2.5.

| Area | Change | Evidence / test |
|---|---|---|
| Paper books | Whole lots: 10 by default (4/3/3), fees for real lots and orders; atomic one-position entry (lock + unique index); freshness re-judged at the decision with a fresh quote; futures quotes need an exchange timestamp; future-dated bars refused; spot-chart levels moved to futures by the live basis, or no trade | `review_round3_response.md` H02–H05, H12, M01; `tests/test_review_round3.py` |
| Option recorder (R1) | Eligible next expiry recorded near expiry; every strike within ±5 strikes of the session's spot range; front future recorded per day | H07 |
| R1 scoring | Fills in time order on one session; finite, uncrossed quotes; each day's front contract; bounded same-session futures quotes; 1.5× spread stress; rupee total | H01, H08 |
| Statistics | One α family R1–R4 (0.0125 each); every test on day means; one look; R3 minimum per group; R4 reports absolute results | M04, M05; `REGISTRY.md` v3 |
| Research code | Entry-bar target (H09); open trade kept on an incomplete day (H10); unresolved `U` exits excluded (H13); fingerprint includes extra expiries (M06); validator rejects inf / non-positive / naive timestamps (M07); stock sizing at the first price (M08). **Re-run: 0 of 9,561 trades changed; sim250 −0.323 → −0.324R; hold-out −0.284 → −0.286R** | `external_result.md` (re-run section) |
| Parity | PARITY now also needs the TradingView trade ledger to match (entry, R, P&L, exit within a tick). Real logs: 25/25 and 13/13 | H11; `golden_parity_*.txt` |
| Evidence cards | Index signals use index-futures evidence only (TradingView, current costs, by window). The old "morning lead" came from stock trades | M11 |
| Delivery and health | Daily report marked only after delivery; Telegram updates acknowledged after handling; health per instrument and for the Telegram loop | M09 |
| Range model | Benchmark on fresh Aug–Oct 2026 (protocol hashed first): ties the linear HAR+VIX model and beats seasonal and VIX-only. M1 (2022–25 fit + conformal) adopted by the pre-declared rule. Guards: official previous close required, complete previous session, gapless today, VIX present | `range_benchmark_result.md`; `test_range_model.py` |
| R6 (new) | Live forward benchmark: M1, HAR+VIX and their average recorded every 15 minutes and scored an hour later; `/range`; scorer `registry_eval_r6.py` | `r6_protocol.md`; `test_r6_*`, `test_live_range_benchmark_*` |
| Reproducibility | Per-trade ledgers (research 53,485; external 9,561; hold-out 504; sim250 260) and a data manifest with SHA-256 of every raw file | `evidence/ledgers/` |
| Docs | `SCOPE.md`; "implemented exactly" corrected to "adaptations" (M10); README v3; evaluator prompt round 4 | — |

# Changelog: v1 → v2 (18 Oct 2026)

v2 answers the three independent reviews (`NFCE_independent_review.md`, `NFCE_improvement_roadmap.md`, the adversarial audit PDF).
- **Fix discipline:** every verified finding was fixed test-first where it is Python. The new test was seen to fail on the old code; mutation testing caught 10 of 10 bridge mutants.
- **Pine checks:** Pine has no unit-test framework. Pine fixes were checked by compiling on TradingView, by the v2 runs (reconciliation counters 0/0/0, including the new quantity check), and by mirroring each rule in the Python engine, which has tests.
- **Parity:** a bar-by-bar Pine-vs-Python test was run on 5,000 exported bars each of NIFTY1! 5m and BANKNIFTY1! 15m. Signals are identical (13/13, 25/25), and so is the position path on every bar. It found and fixed two engine differences (rows at the end). See `PHASE7` §D2.
- **Test counts (final, 20 Oct 2026):** engine 89 tests, bridge 122 tests, all passing.

**What did not change:** the verdict. No configuration shows a net edge (`PHASE7_V2_EVIDENCE.md`).

## Findings → fix → test
Rev = `NFCE_independent_review.md` (C/H/M/L IDs); Aud = adversarial audit (F-IDs).

| ID | Finding | Fix | Test / check |
|---|---|---|---|
| F-01 (Aud) | Paper trades tracked on spot / weekly synthetic forward → fake stops from basis | Paper books follow the live **front-month futures quote**; basis = futures − spot from quotes; no quote → no executable trade, signal UNCHECKED | `test_F01_no_fake_stop_from_spot_vs_futures_basis`, `test_F01_without_quotes_…` |
| F-02 / H02 | `httpx` timeouts escaped and killed the poll loop | `_get` wraps every `httpx.HTTPError` as `ProviderError`; every worker step isolated (`_safe`), heartbeats, 503 health | `test_F02_H02_timeouts_never_kill_the_worker_or_drop_signals`, `test_raw_timeouts_become_provider_errors` |
| F-03 / M02 | Shipped presets were the post-hoc "stricter" ones | Spec presets restored (5m 65/1.5, 15m 60/1.3) in Pine and engine; stricter = labelled `strict_phase3` only | `test_spec_defaults_restored`; TV META shows minScore 65/60 |
| F-04 / H01 | Phase 6 provenance: "3 years" vs a 730-day request | Data manifest with SHA-256, rows, range, sessions, requested period; every tool prints it; Phase 6 corrected (PHASE7 §E) | `test_manifest_hash_is_checked_on_load` |
| F-05 / M03 | Global "force expiry today" rewrote all history | Date list `Extra expiry dates` (Pine) / `extra_expiry_dates` (engine) | compile; engine expiry tests |
| F-06 | Same-bar exit + re-entry, overwritten event strings | No same-bar re-entry by default; immutable trade IDs; event arrays; v2 JSON with `closed` | `test_no_same_bar_reentry_v2_but_legacy_allows_it`; bridge `test_l02_closed_event_inside_a_signal_…` |
| F-07 / H03 | Overnight carry / missed square-off booked as profit | UNRESOLVED status on a later session or an outage across 15:15, excluded from results | `test_H03_F07_overnight_carry_is_unresolved_not_profit`, `test_outage_spanning_square_off_then_restart_next_morning` |
| F-08 / M11 | Reconciliation counters only flat/non-flat | `mmQty`: remaining contracts after T1/T2 must equal the state machine's | TV v2 runs: 0/0/0 on all four |
| F-09 / M12 | Signed ΔOI-PCR ratio semantics | Explicit four-quadrant flow states; unavailable ≠ neutral; boost needs strict unwinding | `test_flow_quadrants`, `test_F09_M12_…`, `test_boost_needs_strict_unwinding_…` |
| F-10 | Spot chart had no volume/OI | Spot index charts use the continuous future automatically; dashboard warns NO VOLUME | compile; dashboard |
| F-11 | Supertrend warm-up | Returns NaN until warmed up, like TradingView | `test_supertrend_direction_follows_trend` |
| F-12 | Login callback server could hang / race | Timeout, path and state checks, atomic 0600 token write | `test_login_flow_end_to_end`, `test_login_error_redirect_and_wrong_path`, `test_login_times_out_…` |
| H04 | Executable book used the signal's old price | Executable entry = live ask/bid + 2 ticks on arrival; stale (>120 s), wide-spread or missing-quote alerts rejected and counted | `test_H04_executable_entry_uses_arrival_price_…`, `test_H04_stale_alert_rejected_…` |
| H05 | Duplicates / concurrent positions | Signal ID dedup in the durable inbox and per book; one position per underlying/timeframe/book; RLock | `test_H05_duplicates_and_manual_checks_…`, `test_book_dedup_persistence_and_day_stats` |
| H06 | Bank Nifty robustness run used `instr="NIFTY"` | Instrument per index in `robustness.py` and `paper_replay.py` | rerun in PHASE7 §B |
| H07 | Moved stop not enforced in the bar that moved it | `Moved stop can trigger in the same bar` (default on), same rule in engine and paper ledger | `test_intrabar_stop_after_target_review_fixture`; paper replay 20/20, 19/19 |
| H08 | 2026 costs applied to 2023–2025 trades | Dated fee schedule (`costs.py`, byte-identical in engine and bridge) plus a separate current-cost stress | `test_reproduces_independent_review_fee_table` (₹966.2155 / ₹980.3542), `test_dated_schedule_is_cheaper_before_april_2026` |
| H09 | Missing prev OI = 0; malformed signals accepted | Missingness preserved → UNCHECKED; signals validated (finite, positive, stop side, R ≤ 5%, ordered targets) | `test_H09_…`, `test_missing_previous_oi_is_unavailable_not_zero`, `test_invalid_signals_rejected` |
| M01 | Cut-offs used bar-open time | Close-time cut-offs (last entry, expiry); lunch excludes bars overlapping 12:30–13:30 | `test_15m_cutoffs_use_entry_time` |
| M04 | Context data not checked for timeframe | `prepare` rejects context frames of another interval | `test_context_must_match_chart_timeframe` |
| M05 | IV change compared across sessions / strikes | Same session, same expiry, 10–20 min window, ATM-shift note | `test_M05_iv_change_is_not_compared_overnight` |
| M06 | Weekly synthetic forward used as monthly basis | Basis from live futures − spot quotes; synthetic forward shown as information only | `test_synthetic_forward_is_information_only`, `test_futures_prices_shifted_by_live_basis` |
| M07 | Receipt time treated as freshness | Exchange last-trade time; quotes older than 90 s = stale (frozen feed / holiday) → no execution | `test_M07_frozen_feed_or_holiday_blocks_execution` |
| M08 | IID statistics only | Day/week block bootstrap, Clopper-Pearson, Holm, mark-to-market drawdown | `test_block_bootstrap_is_wider_for_clustered_days`, `test_holm_and_clopper_pearson`, `test_mtm_curve_…` |
| M09 | Noise test mislabelled and asymmetric | Bounded, tick-rounded `shift`/`jitter`, precision/recall/Jaccard with timing tolerance, P&L distribution | `tests/test_robust.py` (3 tests) |
| M10 | Secret in URL logs; group senders; no durable queue | Access log off + key redaction filter; private chat + sender allowlist; body/rate limits; durable SQLite inbox before reply | `test_M10_telegram_ignores_groups_and_other_senders`, `test_webhook_security_and_durable_inbox`, `test_inbox_survives_processing_crash` |
| L01 | Grade hard-coded; prepared data reusable with other params | Grade uses `a_plus`; config fingerprint guard | `test_grade_uses_a_plus_param`, `test_prepared_fingerprint_guard` |
| L02 | Event strings overwritten | Event arrays + trade IDs; nested `closed` event recorded by the bridge | `test_l02_closed_event_inside_a_signal_is_recorded_and_shown` |
| L03 | Empty Yahoo response crashed | `nfce/data.py`: validate before saving (empty, columns, NaN, duplicates, order, OHLC, grid, session) | `tests/test_data.py` (5 tests) |
| Spec §6 | Daily stop missing | 2 losing trades or −2R per day, cap 4, last entry 14:45, `/halt` (Pine, engine, bridge risk gate) | `test_daily_stop_two_losses_or_minus_2R`, `test_daily_stop_blocks_after_two_losses`, `test_daily_stop_minus_2R` |

## Found during v2 (not in the reviews)
| Issue | Fix | Test / check |
|---|---|---|
| Pine Instrument input defaulted to NIFTY on every chart: on BANKNIFTY it used Nifty's weekly expiry and heavyweights | `Instrument = Auto` from `syminfo.root`; per-instrument heavyweight lists; dashboard shows the instrument | TV v2 META `instr=BANKNIFTY` on BANKNIFTY1! |
| H-A opening-volume gate passed vacuously without volume (0 ≥ 1.5 × 0) | Refuses bars without volume; needs median > 0 | `test_ha_volume_gate_cannot_pass_vacuously_…` |
| `paper_replay.py` called removed v1 bridge methods | Rewritten for the v2 API | replay 20/20 NIFTY, 19/19 BANKNIFTY |
| Float rounding in the one-tick trade-through (110.1 − 110 = 0.0999…) | EPS 1e-9 | `test_executable_target_exact_one_tick_through` |
| Simple-ideas Holm line could present a significantly *losing* rule as "surviving" | Prints the direction ("LOSES money") | output in PHASE7 §C |
| Golden parity: equal up/down moves gave +DM through float noise (+DI/ADX off on 2.5% of NIFTY 5m bars) | Tolerance far below one tick in `ta.dmi` | `test_dmi_equal_up_and_down_moves_count_as_neither_despite_float_noise` |
| Golden parity: previous-day levels rebuilt from intraday bars; TradingView uses daily bars (futures settlement close), 2 of 13 NIFTY signals differed | `prepare(daily=...)` | `test_previous_day_levels_come_from_daily_bars_when_given`; parity 13/13 and 25/25 signals |
| First live login: "Token exchange failed: HTTP 401" hid Upstox's reason | Login prints Upstox's error code, message and a plain hint (used/expired code, wrong key/secret, no active segment); never echoes secrets | `test_login_token_error_shows_upstox_reason_and_hint_not_secret` |
| No timestamped option bid/ask for the option experiment | Bridge records ATM ± 5 strikes (bid/ask/LTP/OI/IV) on every chain refresh | `test_chain_refresh_records_option_quotes_for_the_atm_window` |

## v2.5 (20 Oct 2026): ideas from the ChatGPT and Gemini reports, tested (final package)
| Change | Evidence / why | Test |
|---|---|---|
| Both reports' factual claims checked against primary sources: Medidala repository numbers match (and show a *train* Sharpe of 0.004 with ₹75 costs); Zarattini et al. abstract matches; STT, Tuesday expiries and the end of Bank Nifty weeklies are correct | `evidence/external_result.md` | — |
| Protocol frozen before any result: 11 rules × 2 indices = 22 configurations, train 2022–24 → validation 2025 → one-shot 2026, all at **current** costs | `evidence/external_protocol.md` (SHA-256 `2d6d199b…`) | — |
| `nfce/research2.py`: S1 σ session-anchor momentum, S2 noise-area momentum (and long-only), S3/S4 Williams prior-day and 3-day swing breakouts, S5 NR7 (and ID/NR4 with ATR floor), S6 Oops gap reversal with VIX gate, S7 weekend/holiday ORB, S8 morning ±0.5% move, S9 late momentum. Next-bar-open fills, stop checked before target, 15:25 exit | Conservative fills, so a result cannot come from optimistic execution | `tests/test_research2.py` (10) |
| `tools/external_run.py`: staged runner; the final stage refuses to run without `--i-accept-one-shot` | Stops accidental peeking at 2026 | — |
| Result: 2 of 22 survive train (S4 NIFTY +0.037R, S6 BANKNIFTY +0.103R on 44 trades); **0 pass validation** | `evidence/external_result.md` | — |
| R5 registered separately for S4 NIFTY before its 2026 data was examined; one-shot result n 44, +0.032R but −13.7 pts per trade, PF 1.09, lower bound −0.25 → **FAIL, closed** | `evidence/r5_protocol.md` (SHA-256 `a0d489a4…`), `REGISTRY.md` | — |
| Option ideas (short straddle, 0DTE condor, OI unwinding, NGE) not testable without option history; the 2:1 ratio spread rejected for safety (net naked short option) | Recorded, not hidden | — |
| Final docs: README (verdict first), round-3 evaluator prompt, both reports in `docs/research_round2/` | — | — |

## v2.4 (20 Oct 2026): R4, range-calibrated targets (registered)
| Change | Evidence / why | Test |
|---|---|---|
| Live-feasible range model (index bars + VIX + calendar, 19 features), re-validated: 2025 R² 0.33 / 77.3% coverage, 2026 one-shot R² 0.37 / 77.9% | `evidence/r4_protocol.md`, `tools/train_range_model.py` | — |
| `bridge/range_model.py`: live features identical to training, completed bars only, ~1 year of history (daily ATR), refusals for stale data, out-of-hours or missing history | Bar-for-bar parity with `ml_study.symbol_frame` at 11 cut points | `tests/test_range_model.py` (9) |
| Every alert shows the next-hour range forecast; new paper book `r4` with the same entry/stop/exits as the executable book and range-sized targets; `/paper` and the daily report compare them | Isolates the effect of targets only | `test_r4_book_opens_…`, `test_r4_without_candle_data_…` |
| **Live finding:** Upstox historical candles lagged a day; guard = previous close from the live quote (`last_price − net_change`) must match the history within 0.25% (measured ≤ 0.20% on 76/76 days) | Without it, the gap / previous-day volatility features would be silently wrong | `test_forecast_refuses_when_history_is_missing_…` |
| Setup checker verifies the model loads with the pinned libraries (numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1) | A saved scikit-learn model loads only with matching versions | live check: all ok |
| Real-data replay, 13–16 Oct (unseen): 28/40 hourly actual ranges inside the 80% band (70%, ±13pp at n=40) | End-to-end live path | — |
| R4 registered: ≥ 100 pairs, mean Δ ≥ +0.05R, one-sided p < 0.0125 | `REGISTRY.md`, `nfce/registry_r4.py`, `tools/registry_eval_r4.py` | `test_r4_paired_rule` |

## v2.3 (20 Oct 2026): machine-learning study on 1.09 million samples
| Change | Result | Test |
|---|---|---|
| `tools/ml_study.py`: direction, range and target-before-stop models; 52 symbols x 4.5 years; train 2022-24 / validate 2025 / final 2026 | Direction: coin flip (AUC 0.49-0.54), every rule loses after costs. Range: **passes** (R² 0.37 and 78% coverage of the 80% band on indices, 2026 one-shot) | `tests/test_ml_study.py` (3 leakage tests) |
| `RESEARCH_BRIEF_FOR_OTHER_AIS.md` | Brief for ChatGPT/Gemini: what has failed, 2026 costs, the exact rule format needed for testing | — |

## v2.2 (20 Oct 2026): fuzzing, failure injection, multi-year research
| Change | Why | Test |
|---|---|---|
| `Signal.from_payload`: non-finite score -> no score; bar time that can't be converted, or falls outside 2000-2100 -> no bar time | **Found by fuzzing:** `{"t": Infinity}` crashed with OverflowError | `tests/test_fuzz_and_faults.py` (12) |
| Event alerts: `events` / `closed.events` may be any type (a number, text, a list); normalised to a list of text | **Found by fuzzing:** a number in `events` crashed processing (the alert stayed in the inbox as ERROR) | same |
| Failure injection: any provider exception (Upstox error, expired token, timeout, malformed data), Telegram down, clock jumping backwards, restart mid-trade | Never crash, never lose an alert, never open a position without data, never book a fill without a reason | same |
| R3 re-registered (rules.py hash), before any live data | Input-validation change only; the veto rule is unchanged | `REGISTRY.md` amendment |
| Research: 84 configurations (NFCE, ORB, momentum, VWAP) on 4.5 years of Upstox 5m data, train/validation/final splits frozen in advance; historical NSE expiry calendar | Find what works, honestly | `nfce/research.py` (8 tests), `evidence/research_*.md` |

## v2.1 (19-20 Oct 2026): evidence-aware signals
| Change | Why | Test |
|---|---|---|
| Every signal leads with an evidence label (🟢 VALIDATED / 🟠 LEAD (unproven) / 🔴 NO EDGE), from a rule fixed in advance; the chain check moves to line 2 | A green "✅ PASS" headline read like "trade this", although it only meant the option chain did not object | `test_every_signal_leads_with_its_evidence_label_and_card`, `tests/test_evidence.py` (7) |
| Evidence card: out-of-sample record of the signal's class (time of day x cost share x index/stock), 95% interval, fallback when a cell is thin | A signal should state how often signals like it have worked | `test_thin_cells_fall_back_…`, `test_trust_labels_follow_the_fixed_rule` |
| Live cost share per signal; costs >= 50% of risk forces NO EDGE | A NIFTY futures round trip is about 16 points; a 30-point stop is half costs | `test_tight_stop_is_labelled_no_edge_because_of_costs` |
| `/trust` command and a live-vs-tested drift warning in the daily report | The system should notice if reality is worse (or suspiciously better) than its tests | `test_drift_flags_live_results_…`, `test_trust_command_…` |
| Engine: optional `min_risk_pct` cost gate (off by default, research only, not in Pine) | Hold-out study (`evidence/holdout_*.md`) | `test_cost_gate_skips_trades_…` |
| Tools: `sim3d.py`, `sim250.py`, `build_evidence.py`; evidence write-ups for 819 simulated trades | Paper simulations with frozen protocols | protocol files hashed before running |

Mutation check of the evidence module: 4 of 4 planted bugs caught by the tests.

## New in v2
- `REGISTRY.md` + `nfce/registry.py` + `tools/registry_eval.py`: three pre-registered experiments, with frozen thresholds, file hashes and mechanical scoring (`tests/test_registry.py`).
- `PHASE7_V2_EVIDENCE.md`: all evidence rebuilt with v2 code; `evidence/tv_v2_base_trades.txt` raw TradingView trades; `tools/tv_evidence.py` re-check.
- `nfce_analysis_v2.js`: in-browser analysis with the dated cost schedule (self-test against `costs.py` reference values).
- Strategy: optional golden bar export (`Golden export: log the last N bars`) for a Python parity test.
