# NFCE option-chain bridge v2 (alerts and paper trading only)

The bridge adds option-chain context to NFCE signals and sends each one to your Telegram with a **PASS / VETO / UNCHECKED** verdict.
- **Data source:** the **Upstox** API.
- **No orders:** it **never places orders**. There is no order code in this package.
- **Runs on your Mac:** alerts-only use needs no VPS and no static IP.

> **Honest status.** No tested signal shows an edge after costs (`../PHASE7_V2_EVIDENCE.md`). The veto/boost rules
> are an **untested hypothesis**, registered as experiment R3 in `../REGISTRY.md`. Use the bridge to paper-trade and
> collect evidence, not to trade real money.

## The control panel: `nfce` (v3.5)
One terminal command for everything: `nfce` opens a menu; `nfce help` lists the commands.

| Need | Command |
|---|---|
| See everything at a glance | `nfce status` |
| Start / stop / restart the system | `nfce start`, `nfce stop`, `nfce restart` |
| Upstox sign-in (you sign in, in the browser) | `nfce login` |
| Is everything aligned? / live test | `nfce check`, `nfce check --live` |
| Find and repair problems | `nfce fix` |
| Logs, Telegram messages | `nfce logs [supervisor] [N] [-f]`, `nfce messages` |
| Accounts, today's results, risk | `nfce accounts`, `nfce report` |
| Tests, after-close study, backup | `nfce test`, `nfce study`, `nfce backup` |
| Optional background self-healing | `nfce supervisor on\|off\|status` |
| New Mac or repair: environment, keys, command | `nfce setup`, `nfce env`, `nfce env set KEY` |

**On a new Mac:** copy the folder, then run `bash nfce_bridge/nfce setup`. It:
- creates the environment with the pinned packages;
- asks for each missing `.env` key (secrets are typed hidden);
- installs the `nfce` command;
- runs the tests and the checks.

## The Telegram bot (v3.4): admin, users, and running without an assistant
**Who can do what**
- **Admin** (`TELEGRAM_ADMIN_CHAT_IDS`, here the "S" chat): everything below, plus control.
- **Users** (the main chat, and anyone the admin adds): signals, reports and read-only commands.
- **Unknown chats:** nothing runs. The admin gets an access request with the chat id.

**Users** can ask in plain words ("profit?", "open positions", "signals today", "gainers", "is it working?"), or use:
- `/today`: today's signals and the account's result;
- `/open`: open positions with live P&L;
- `/account` or `/pnl`, and `/ledger`;
- `/watch`, `/scan`;
- `/status`, `/range`, `/health`;
- `/explain`, `/about`;
- `/risk`: open positions by direction, and the loss if every stop is hit (v3.5);
- `/meme`: a little trading humour (the signals stay strictly professional) (v3.5);
- `/ask <msg>` to reach the admin;
- `/stop` and `/start` for their own messages;
- `/myid`.

A longer message is saved as a note and forwarded to the admin.

**When the system is offline** (v3.5): a separate small process, `python -m bridge.offline_bot`, answers while the bridge is stopped:
- **Commands:** `/status`, `/account`, `/today`, `/risk`, `/about`, `/ledger` (admin), `/meme`, `/help`.
- **Other messages:** saved for the admin and the assistant.
- **Polling:** it polls Telegram only while the bridge's `/health` does not answer, so the two never compete; it shares the bridge's update offset.
- **Starting it:** `nohup .venv/bin/python -m bridge.offline_bot >> ~/Library/Logs/nfce_offline_bot.log 2>&1 & disown`.
- **Limit:** it does not keep the Mac awake, and it does not survive a reboot (a launchd agent would).

**Self-healing (v3.5):** the same process supervises the bridge on weekdays 09:15–15:15.
- **Dead bridge:** if a bridge that already ran today dies (no process for 60 s), it restarts it, at most 3 times a day.
- **Hung bridge:** if the market loop goes silent for 5 minutes, it stops the bridge and `start.sh` restarts it.
- **Messages:** the admin is told each time.
- **Deliberate stop during market hours:** `touch ~/.nfce_maintenance` first.

**Preflight:** `python -m bridge.preflight` checks that everything is aligned before a session (see its docstring); `start.sh` runs it.

**Admin commands**

| Need | Command |
|---|---|
| Stop or allow new entries (paper books and accounts) | `/pause`, `/resume` |
| Sell open positions now at the bid | `/close <n\|all>` (asks for a confirmation code) |
| Account settings (bounded, kept after a restart) | `/set risk 0.5`, `/set losslimit 2`, `/set maxopen 3`, `/set costgate 0.2`, `/set deploy 50`, `/set stockrisk 0` |
| Switch a feature without a restart | `/toggle index\|stocks\|scanner on\|off` |
| Users | `/users`, `/adduser <id>`, `/removeuser <id>`, `/mute <id>`, `/unmute <id>`, `/broadcast <text>` |
| Information | `/report`, `/export` (ledger + signals CSV), `/notes`, `/errors`, `/config` |
| Maintenance | `/backup`, `/restart` (confirmation code), `/reset [capital]` (confirmation code) |
| **Upstox sign-in from the phone** | `/login`, sign in on Upstox's page, then copy the 127.0.0.1 address the browser shows (it will not load, which is expected) and send `/code <address>` |

**Jobs that run on their own**
- 08:00–15:30: a token check, with a `/login` reminder to the admin.
- 09:05: a morning brief to everyone.
- During the market:
  - a health watchdog alerts the admin after 3 minutes of a problem, and again when it clears;
  - an alert on a burst of errors.
- 15:20: the daily report.
- 15:35: the ledger to the admin, plus a database backup (`data/backups`, the last 10 kept).

**`start.sh`** keeps the Mac awake (`caffeinate`) and restarts the bridge after a crash or `/restart`. It gives up after 5 quick failures in a row. If the Upstox login is not completed at the start, the bridge runs anyway: sign in with `/login`.

`ASSISTANT_RELAY=on` adds "passed to your assistant" to `@admin:` notes. Set it to off when nobody reads them.

## Trust: what every signal tells you (v2.1)
Every alert opens with an **evidence label**, not with the option-chain check:
- 🟢 **VALIDATED**: the signal's class passed a registered live experiment (`REGISTRY.md`). **No class has passed yet.**
- 🟠 **LEAD (unproven)**: signals like this had an edge before costs (≥ +0.10R on ≥ 30 unseen trades), and their after-cost interval still reaches above zero. Worth paper-testing; not shown to make money.
- 🔴 **NO EDGE**: signals like this lost money after costs on unseen data, or this signal's costs eat half or more of its risk.

**The evidence card under the headline shows:**
- the measured record of signals like it: trade count, winners, gross and net R with a 95% interval, from 504 hold-out trades (`bridge/evidence_table.json`, built by `nfce_engine/tools/build_evidence.py`);
- the share of *this* signal's risk that costs will eat, from the dated fee schedule;
- for NIFTY / BANKNIFTY: index-futures evidence only (94 TradingView trades, current costs, by entry window). Stock trades never stand in for an index.

**When a class has too few trades,** the card says so and uses the broader class.

**`/trust`** shows the whole evidence base and the live paper record. **The daily report** flags it when live results drift outside the tested range, worse or better.

## New (20 Oct 2026): signals without paid TradingView, SENSEX, option legs, F&O scanner
- **Own signals.** With `ENGINE_UNDERLYINGS=NIFTY,SENSEX`, the bridge runs the NFCE engine itself on live Upstox futures candles: 5m and 15m, about 20–35 s after each bar closes. The engine equals the TradingView strategy bar for bar, and `tests/test_live_engine.py` proves the live feed emits exactly the batch engine's trades.
  - These signals go through the same path as TradingView alerts: chain check, evidence card, range forecast, paper books.
  - The free TradingView plan has no webhooks, so this is how signals arrive automatically.
- **SENSEX.** BSE_INDEX|SENSEX spot, the BSE future (lot 20, tick ₹0.05), the BSE option chain. It is untested historically, and its cards say so.
- **Option legs** (`OPTION_LEGS=on`): every signal shows the 1-ITM option to buy (call for BUY, put for SELL) at the nearest expiry after today: live bid/ask, and SL/T1/T2/T3 mapped from the underlying's levels through the live delta.
  - The `options` paper book buys at the ask when the futures paper trade opens, and sells everything at the live bid when it closes.
  - The leg is skipped if the spread is above 5% of the premium.
  - `/options` shows the results.
- **F&O scanner** (`SCANNER=on`): at 10:15, 11:15 and 13:15, the top 5 gainers, top 5 losers and top 5 volume surges among all ~246 F&O stocks, each with futures levels and an option leg, all paper-traded (book `scanner`).
  - The rules were tested first, and **lose after costs** (`evidence/scanner_result.md`). Every scan message says so.
  - `/scan` shows the lists at any time (analysis only).
  - The scanner loads about a month of 5m history per stock once a day in the background, about 2 minutes after the first tick.
- **Free-text Telegram messages** are saved as notes and acknowledged, not answered with the help text.

## Next-hour range forecast and the R4 book
- **Every alert shows the forecast next-hour range** for its index, e.g. "median 62 pts, 80% band 41-110 pts". The model behind it, M1:
  - gradient-boosted quantile regression, fitted on 2022–2025 and calibrated on Jan–Jul 2026;
  - on fresh Aug–Oct 2026 data its 80% band held 77% of real moves (about 69% after 13:00);
  - level with a simple linear HAR+VIX model (`evidence/range_benchmark_result.md`);
  - forecasts how *far* the market is likely to move, not which way.
- **R6 live scorecard:** at every decision bar (closes 09:45–14:15, every 15 minutes) the bridge records M1, the linear model and their average for both indices, and scores each forecast an hour later. `/range` and the daily report show the scorecard.
- **Book `r4`:** whenever the executable paper book enters, `r4` enters at the same price with the same stop and exits. Its targets are sized to the forecast instead of 1R/2R/3R. `/paper` shows the paired comparison; registered experiment R4 decides after 100 pairs.
- **When the forecast can't be trusted,** it says so: stale bars, outside 09:45-14:15, Upstox history missing or incomplete for yesterday, no official previous close, gaps today, or no VIX. That signal then gets no R4 trade, and the reason is recorded.

## What it does
1. **Polls the market (09:15–15:30 IST, Mon–Fri).**
   - **Every 15 s:** one quote call for the front-month **future** (the contract NIFTY1! follows), the spot index and India VIX.
   - **Every 60 s:** the nearest-expiry option chain.
   - Expiries come from Upstox's contract list, so holiday shifts are handled. The front future comes from Upstox's public instruments file.
   - **Freshness:** data is fresh only if the exchange's last-trade time is under 90 s old. A frozen feed or a holiday blocks execution.
2. **Summarises the chain (ATM ± 5 strikes):**
   - PCR by OI;
   - change-in-OI flow in four states (put/call writing vs unwinding);
   - the call and put OI walls and whether they are building;
   - max pain;
   - ATM IV and its 15-minute change (same session and expiry only).
   - If any strike lacks a previous OI, the flow is **unavailable**, never "zero".
3. **Checks each signal.** Futures prices are shifted to spot terms by the **live basis** (futures − spot quote).

   | Side | VETO when | BOOST (A → A+) when |
   |---|---|---|
   | BUY | flow bearish (calls written / puts unwinding, PCR(ΔOI) < 0.7) **and** a building call wall between entry and T1 | puts written below entry **and** call OI strictly unwinding above it |
   | SELL | mirror image (PCR(ΔOI) > 1/0.7) | mirror image |

   No chain, no basis or no ΔOI → **UNCHECKED**. A signal is never passed silently.
4. **Paper-trades every TradingView signal in two books** (`bridge/paper.py`), in **whole lots: 10 by default (4/3/3 at T1/T2/T3), as in the strategy** (`PAPER_LOTS`). Fees are charged for the real lots and orders.
   - **Price domain:** an alert from a futures chart (NSE:NIFTY1!) carries futures prices. An alert from the spot chart (NSE:NIFTY) has every level moved to futures with the live basis; with no basis, no paper trade.
   - **Theoretical book:** enters at the signal price and manages exits exactly like the backtests (40/30/30, BE after T1, trail to T1 after T2, 15:15 square-off). Dated fees plus 4 ticks per side.
   - **Executable book:** what you could really have done.
     - **Entry:** the live ask/bid + 2 ticks, from a quote fetched again at the moment of decision.
     - **Entry is refused** if:
       - the decision comes more than 120 s after the bar closed, or the bar time is in the future;
       - the quote has no exchange timestamp or is stale;
       - the spread is too wide;
       - the price is already beyond SL/T1;
       - the **risk gate** says stop.
     - **One position per index and timeframe,** enforced by one lock and by the database.
     - **Exits:** targets need a one-tick trade-through; stops exit at the touch (SL-M, never better than the stop).
   - **Risk gate:** stop for the day after 2 losing trades or −2R; at most 4 trades a day; no entry after 14:45; `/halt` and `/resume`.
   - **UNRESOLVED:** a trade still open on a later session, or across an outage spanning 15:15, is never booked as profit or loss. It is excluded and counted separately.
   - **Vetoed signals are booked as shadow trades,** so the veto is measured (R3), not assumed.
5. **Stores everything in SQLite** (`data/nfce.db`):
   - **inbox:** every webhook is written here *before* the reply, deduplicated by signal id, and recovered after a crash or restart;
   - **snapshots, quotes, signals and events;**
   - **option_quotes:** bid/ask/LTP/OI/IV, both types, on every chain refresh, for every strike within ±5 strikes of any spot price seen that session. Within 2 days of expiry, the next expiry is recorded too. This is the data experiment R1 needs. It grows by about 2–4 MB a day per underlying;
   - **contracts:** which futures contract was the front month on each day;
   - **range_forecasts:** the R6 forecasts and their realised outcomes.

## Getting signals into the bridge
| Route | Needs | How |
|---|---|---|
| **Telegram (free)** | Nothing extra | `/check BUY 24512 24480` (side, entry, SL, optional T1, optional NIFTY/BANKNIFTY), or paste an alert's JSON. **Analysis only:** manual checks never open paper trades. |
| **TradingView webhook (automatic)** | A paid TradingView plan (webhooks), plus a public HTTPS URL | Run a tunnel, e.g. `cloudflared tunnel --url http://127.0.0.1:8000`. Alert: *Any alert() function call*. Webhook URL: `https://<tunnel-host>/tv?key=<WEBHOOK_SECRET>`. The bridge stores the alert and answers at once. Access logs are off and the key is redacted from any log line. |

Bot commands:
- `/status [NIFTY|BANKNIFTY]` shows the latest chain summary.
- `/paper` shows both books: taken vs vetoed, and the R3 veto test.
- `/health` shows worker heartbeats and data freshness.
- `/trust` shows what the evidence says about these signals, and live vs tested results.
- `/range` shows the live range-forecast scorecard (R6).
- `/halt` and `/resume` control the risk gate.
- `/help` lists the commands.

The bot answers only **private** messages from `TELEGRAM_CHAT_ID`, plus any user ids in `TELEGRAM_ALLOWED_USER_IDS`.

## Setup (once)
1. In Terminal:
   ```bash
   cd ~/Downloads/nfce/nfce_bridge
   bash setup.sh
   ```
   This creates `.venv`, installs the packages, generates `WEBHOOK_SECRET`, runs the tests and lists what is missing.
2. **Telegram:**
   - Create a bot with **@BotFather** and paste its token into `.env` as `TELEGRAM_BOT_TOKEN`.
   - Send your bot any message.
   - Run `.venv/bin/python -m bridge.check_setup --find-chat-id` and paste the number as `TELEGRAM_CHAT_ID`.
3. **Upstox:**
   - Developer portal → **Apps → New app**.
   - Redirect URL exactly `http://127.0.0.1:8765/callback`.
   - Paste the API key and secret into `.env`.
4. **Check everything:** run `.venv/bin/python -m bridge.check_setup`. Every line should read `[ok]` and a test message should arrive on Telegram. The checker never prints secrets.

You paste the keys into `.env` yourself. Never send them to anyone, including an AI.

## Every trading day
```bash
cd ~/Downloads/nfce/nfce_bridge
bash start.sh
```
- If today's token is missing, this opens the Upstox login first. Tokens expire at **03:30 IST**.
- Ctrl+C stops the bridge. The inbox and open paper trades survive restarts.

## Scoring the registered experiments
After enough live paper trading, run:
```bash
cd ../nfce_engine
python tools/registry_eval.py r3 --db ../nfce_bridge/data/nfce.db
```
It prints PASS / FAIL / INCONCLUSIVE against the frozen criteria in `REGISTRY.md`. R1 needs the same database plus NIFTY 60m bars.

## Tests
`.venv/bin/python -m pytest -q` runs **185 tests**, including randomised fuzzing of every alert and command and failure injection. They cover:
- one regression test per reviewer finding (`tests/test_review_regressions.py`, and `tests/test_review_round3.py` for round 3);
- every paper-trading exit rule and both books;
- restarts, outages and overnight carries;
- the durable inbox and deduplication;
- the risk gate;
- the real HTTP paths against fake Upstox and Telegram servers, including timeouts, token errors and the browser login flow;
- chain parsing, missing previous OI, the four flow states;
- every veto/boost branch;
- signal validation;
- webhook authentication and limits;
- Telegram sender filtering;
- option-quote recording.

## Compliance note
- Alerts plus manual orders need no static IP and no algo registration.
- If you ever automate orders, SEBI's retail algo framework requires a broker-whitelisted **static IP** and a registered algo / API key. A home connection won't qualify.

## Verified live (19 Oct 2026, after hours)
- **Endpoint access:** login, option chain, market quotes and the instruments file all work with a normal Upstox account.
- **Field names:** the chain response has `bid_price` / `ask_price` (and `bid_qty`, `ask_qty`, `prev_oi`, greeks). All 144 NIFTY strikes parsed with both prices.
- **Front future:** found from the instruments file (NIFTY FUT 27 OCT 26, lot 65); live basis = futures - spot quote.

## Not verified yet
- **Market hours:** quote freshness, the executable book and the risk gate in a live session. The first market session is the test.
- **Other underlyings:** the keys for FINNIFTY, MIDCPNIFTY and SENSEX. Only NIFTY and BANKNIFTY were backtested.
- **After the close on an expiry day,** the "nearest expiry" is still the day's own, now expired, series until midnight. That is harmless, because the bridge only trades in market hours.
