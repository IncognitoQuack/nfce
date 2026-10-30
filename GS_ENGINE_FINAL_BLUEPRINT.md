# GS engine: final blueprint (v1.0, 26 Oct 2026)

**Status:** APPROVED by the owner on 26 Oct 2026 with the recommended defaults (₹10 L OVN book, ₹1 L SIP ticket, pilot-then-final test lengths). Build of phases 0–4 starts after that day's close. Nothing is registered until each phase's protocol is hashed.
**Sources:**
- `GS_engine_blueprint.md`: called **A** below; the backbone, because it is the more rigorous of the two.
- `gs_series_engine_blueprint.md`: called **B**; its practical pieces are kept, its unmeasured profit claims dropped.
- Today's measurements on live data (section 2).
- The NFCE evidence files.

**What "tested" means here:** every number in section 2 was measured today on recorded live data, and four of A's code findings were checked against our code. The design is not a profit test. Profit can only be shown by the forward tests in section 9.

---

## 1. The decision, in plain English
- **GS is a research-and-risk engine that is allowed to stay in cash.** It trades on paper only, in its own books, separate from the six accounts.
- **Four candidate edges, built and tested one at a time, in this order:**
  1. **SIP:** stocks-in-play breakout, cash equity, limit-order entry.
  2. **OVN:** overnight NIFTY iron fly with bought wings.
  3. **RANGE:** range forecast vs option prices. A measurement first; trading only if the measurement passes.
  4. **NEWS:** results and filings with real timestamps.
- **None of them is proven.** The blueprint makes **no profit forecast**. B's figures ("+2.5 to 5.5 bp", "+0.05 to 0.12R") were never measured and are not used.
- **They are not independent.** SIP and NEWS are both stock-momentum bets; OVN and RANGE are both short-volatility bets. The risk limits treat each pair as one risk.
- **Build order:** data integrity, costs, execution and risk first; then one edge at a time.
- **The honest cost of proof:** confirming a small edge takes years of forward data (section 9). Short pilots can only kill bad ideas early or reveal large edges.

## 2. Feasibility checks run today (26 Oct, live recorded data)
| Check | Measured | Consequence for the design |
|---|---|---|
| Cash-equity half-spread, F&O stocks (`study_quotes_20261026.db`) | Median **1.9 bp** before 09:30 (90th percentile 5.3); **2.1 bp** 09:30–10:00; **1.9 bp** 10:00–11:30; **1.7 bp** 11:30–14:00 | Cash equity is the right vehicle (stock futures were ~4.6 bp). The opening 15 minutes have the widest tail, so SIP triggers start at 09:30, as A proposes. |
| Displayed 5-level depth (smaller side) | Median **₹4.3 L** in total | A's cap of "≤10% of displayed depth" would allow a ₹1 L ticket only **24%** of the time, and ₹3 L only 6%. Too strict: NSE displayed depth hides refreshing liquidity. **Changed** (section 6). |
| Traded value per minute, F&O stocks, 09:30–11:30 | Median **₹27 L**/min (25th percentile ₹10 L) | Ticket ≤5% of trailing traded value per minute: a ₹1 L ticket fits 59% of stock-minutes overall, and more for in-play stocks. Adopted as the capacity rule. |
| OVN mechanics (NIFTY 3 Nov expiry, 13:22 snapshot, spot 22,641) | Wings = 1×ATR14 (289) → W = 300: credit **₹15,402**, max loss **₹4,098/lot** (+ about ₹500 fees); summed spread of the 4 legs 2.5 pts. With W = 450: credit ₹20,569, max loss ₹8,681. | A's budget (0.5% of ₹5 L = ₹2,500) is **smaller than one lot's risk**, so OVN can never trade at ₹5 L. **Decision needed:** a ₹10 L virtual OVN book (0.5% = ₹5,000 fits one W = 300 lot). |
| A's code findings (4 of 10 checked) | All 4 confirmed: `study2.py` passes `open_entry` as all-false; `overnight_options.py` pairs consecutive files and falls back to LTP; the recorders stamp time **before** the request (`collect.py:55`, `collect_chain.py:51`) | Phase 0 fixes them and versions the affected tests. The other 6 findings are checked in phase 0. |
| Brokerage | Upstox intraday: ₹20 per order or a % of turnover, whichever is lower; sources disagree on the % ([Upstox calculator](https://upstox.com/tools-and-calculators/brokerage-calculator/), [Chittorgarh](https://www.chittorgarh.com/stockbroker/upstox/33/)) | The fee module uses ₹20/order and is checked against Upstox's official tariff page before any test is locked. |

## 3. Architecture (A's layout, with B's useful parts)
One pure-Python package, `nfce_engine/gs/`, imported by both the research tools and the bridge. No new dependencies, and no order code.

| Module | Job | Source |
|---|---|---|
| `gs/types.py`, `calendar.py`, `instruments.py` | Immutable events; exchange calendar (sessions, holidays, expiries); lot/tick per date | A |
| `gs/store.py` | Append-only SQLite event store (WAL): `events`, `intents`, `execution_events`, `positions`, `day_equity`, `protocols`, `verdicts` | A |
| `gs/features.py` | As-of features (ATR14 Wilder, opening RVOL, ER20, VIX state, chain summary); each feature records the latest `available_at` it used | A + B's `MarketStateSnapshot` |
| `gs/costs.py` | Per-fill fees by effective date (STT, exchange, SEBI, stamp, GST, ₹20 brokerage); wraps the existing `costs.py` without changing the frozen functions | A + B |
| `gs/execution.py` | Book walking, capacity, three passive-fill scenarios, multi-leg state machine (wings first) | A + section 6 |
| `gs/ledger.py`, `gs/risk.py` | Signed legs, cash, reserves, unresolved exposure; limits, DG latch, loss latches | A |
| `gs/alpha_sip.py`, `alpha_ovn.py`, `alpha_range.py`, `alpha_news.py` | Pure `propose(snapshot, state, config) -> [Intent]` | A |
| `gs/evaluate.py`, `gs/registry.py` | Stationary block bootstrap, power check, one-look lock, hashed manifests | A |
| `gs/allocation.py` | Shrinkage allocator; zero until something passes | A |
| `bridge/gs_adapter.py` | Called from the bridge tick inside a try/except. A GS failure can never touch the six accounts. | A |
| `bot.py` additions | `/gs` (books, open intents, health) and `/gsbrief` (news brief) | B |
| `tools/gs_replay.py` | Replays recorded events through the same functions (parity with live) | A |

Interfaces are as in A section 3: `features_asof`, `propose`, `approve`, `simulate`, `apply_event`, `evaluate`. The rule: **no function can read data later than its decision time**, and replay gives byte-identical intents and fills.

## 4. Data and timing rules
1. **Recorders store three times:** request start, response received, and exchange time when given. Option legs in one structure must be ≤2 s apart. Decisions use quotes ≤2 s old (live refresh before any fill).
2. **Older archives** (minute snapshots up to today) are **exploratory only**: they cannot prove fills.
3. **Universe:** the current F&O list is fine for forward tests. Historical results are labelled "today's survivors".
4. **Request budget:** one shared token bucket, ≤1,600 requests per 30 minutes across the bridge and all recorders. Exits first, then health, active positions, chains, and warm-up last. An HTTP 429 freezes new entries.
5. **Missing data never vanishes from P&L.** Positions stay open as "unresolved", with a conservative reserve. A result that could flip under an adverse resolution is INCONCLUSIVE.

## 5. The four edges (exact rules)
### GS-SIP-1: stocks in play, cash equity, passive entry (A section 6, with changes)
- **Selection at 09:21:**
  - eligible: F&O cash stocks with the first two 3-minute bars and 14 previous valid opening windows;
  - `RVOL = (09:15–09:21 volume) / mean of the same window over 14 sessions`, at least 1;
  - ATR14 (Wilder, previous days) / previous close at least 1%;
  - keep the top 20 by RVOL (ties by instrument id); direction = sign(09:21 close − 09:15 open), with 0 meaning skip.
- **Entry:**
  - trigger: the first completed 3-minute close beyond the opening-range boundary, from **09:30** to 11:30;
  - passive limit at `min(boundary, bid)` for a long or `max(boundary, ask)` for a short, active after 2 s, expiring after 180 s or at 11:33;
  - no chasing and no second attempt.
- **Exit:** stop at fill ± 0.5×ATR14; no target; exit at 15:15 at the touch.
- **Size and limits:**
  - ticket ≤ ₹1 L, also capped by section 6 capacity and section 7 risk;
  - at most 4 open positions;
  - **branch M:** the same signals with a marketable entry (this replaces the separate H2 account brief).
- **Score every opportunity:** unfilled trades count as zero in the primary series, and missed winners are reported.

### GS-OVN-1: overnight NIFTY iron fly (A section 7, sized from section 2)
- **Entry:**
  - decide at 15:20, all 4 legs within 2 s, cancel at 15:21;
  - expiry: the nearest one strictly after the next exchange session;
  - ATM strike K; wings at K ± (1×ATR14 rounded up to the strike step);
  - enter only if `0 < credit < width`;
  - paper order of legs: **wings first, shorts second**.
- **Skip when:** previous-close VIX > 25, or VIX up more than 20% over 5 sessions, or a known event spans the night (RBI policy, Budget, election counting).
- **Exit:** from 09:20 on the next **exchange** session (from the calendar, not the next data file); shorts closed before wings.
- **Size and limits:** **₹10 L virtual book**, risk budget 0.5% (₹5,000) per structure including the fee reserve; one lot max at today's levels.
- **This version replaces** today's `overnight_options` protocol as a v2. The v1 file stays in REGISTRY with an amendment note.

### GS-RANGE: measurement first (A section 8 Stage A)
- **Measurement:** log, per hour, the model's forecast, the option-implied proxy, and the realized range, variance and option round-trip. **No trades.**
- **The trading candidate** (A's 10:30 iron fly with a ridge forecast of net P&L) is registered **only if** the measurement shows the disagreement predicts realized-vs-implied (C3 of `range_vs_implied_protocol.md`).

### GS-NEWS-1: delayed continuation after filings (A section 9)
- **Events:**
  - categories: Financial Results and Outcome of Board Meeting, events 09:30–13:30;
  - the event must have been received within 120 s of dissemination.
- **Signal:** abnormal 5-minute move vs the NIFTY future `|AR5| ≥ 0.40%`, in the direction of the move.
- **Entry:** at a **later** quote than the one that completed the signal, ≥2 s after it.
- **Exit:** stop 0.5×ATR14; out at t0 + 60 min or 15:15.
- **Size:** ₹1 L ticket; one news position per stock per day.
- **B's XBRL surprise sign** (profit and revenue YoY from `news_brief.py`) is **recorded as a stratum**, not used as a filter in v1. That avoids spending a second claim on an unproven condition; it can become v2.

## 6. Execution
- **Marketable fills:** walk the 5-level book after the latency.
- **Capacity** (changed from A, using section 2):
  - ticket ≤ 5% of the trailing 5-minute average traded value per minute;
  - impact from walking the book ≤ 3 bp (B);
  - if it doesn't fit, take a partial size or skip.
- **Passive fills,** reported as three scenarios. Only the strict and stress scenarios can pass a test:
  1. **Touch:** optimistic, an illustration only;
  2. **Strict-through:** the price must trade through the limit by at least one tick, with size;
  3. **Adverse stress:** strict-through, with the best 25% of filled outcomes removed and a 2 bp penalty.
- **Order-book imbalance (B's GS-A5)** is **recorded at every decision** as a diagnostic. It becomes a gate only after its own test.
- **Markouts:** after 10 s, 1 min and 5 min for every fill.

## 7. Risk and portfolio (A section 10)
- **Regime map:**
  - VIX ≤ 20: full size;
  - VIX 20–25: half size;
  - VIX > 25 or up more than 20% in 5 days: quarter size for SIP and NEWS, and no new short-volatility trades;
  - events block entries;
  - an expiry-day contract is never used.
- **Diagnostics only in v1:** B's trend/chop (ER20) and A's range bands, logged but not acted on.
- **Cash sizing:** risk 0.25% of equity per trade; stress loss = stop + 0.25 ATR + friction + fees.
- **Portfolio caps:**
  - gross ≤ 100% of equity, net ≤ 50%, one stock ≤ 20%, one sector ≤ 30%, at most 4 open;
  - cash stress loss ≤ 1%; option reserves ≤ 1%; everything together ≤ 1.5%;
  - correlated clusters (ρ ≥ 0.7 or same sector) ≤ 0.5%;
  - OVN and RANGE share one short-volatility cap.
- **Loss controls:**
  - DG latch per book;
  - day loss ≥ 1.5%: no new entries;
  - drawdown ≥ 5% from peak: pause until review.
- **Stress grid:**
  - spot −10% to +10%, IV −10 to +40 points, spreads ×1, ×2 and ×5;
  - delays and a one-session outage;
  - two maximum-loss nights in a row, a failed wing fill, and a Mac sleep or token expiry mid-trade.

## 8. Allocation and the LLM
- **Allocation:** real allocation stays at **zero** until an edge passes its final test. After that, A's shrinkage allocator applies: at most 50% of capital deployed, at most 25% per edge, at most 25% for short volatility, steps of no more than 5 points per 60 sessions. No Kelly sizing, bandits or reinforcement learning.
- **The LLM** is used only to **extract numbers from filings** (checked by a deterministic parser) and to write owner summaries. Before use it must reach ≥99% exact on 200 forward filings. It never picks trades in v1.

## 9. Testing: how each edge is judged
- **Stage 1, pilot (60 sessions):** check data quality, fill rates, fee accuracy, feasibility, and the variance of the daily result. **Futility stop:** if the pilot's mean is clearly negative (upper 90% bound < 0 under strict fills), close the edge. Stopping a loser early does not risk a false pass.
- **Stage 2, validation (next 60 sessions, rules frozen):** continue only if:
  - total net P&L is positive under strict fills;
  - it is still positive with spreads ×1.5;
  - coverage is ≥ 95%;
  - there are ≥ 100 trades (SIP/NEWS) or ≥ 20 structures (OVN).
- **Stage 3, final (fixed N from the pilot's variance, using A's power formula):**
  - one look only, at α = 0.003125 per claim (A's budget of 16 claims);
  - stationary block bootstrap: block 5, robustness hurdles at blocks 10 and 20, seed 20261026;
  - planning N: SIP 1,000, OVN 700, RANGE 1,000, NEWS 700 sessions; recomputed after the pilot, before the final starts;
  - if the power is too low within 5 years, the result is INFEASIBLE, stated honestly.
- **Verdicts:** PASS, FAIL, INCONCLUSIVE or INFEASIBLE. No extensions after seeing results, and any rule change starts a new version with a new sample.
- **What the owner sees each week:** pilot progress, fills, costs and plain daily P&L, clearly labelled "not yet evidence".

## 10. Build phases (each shippable; tests first; both suites green; CHANGELOG + REGISTRY)
| Phase | Content | Est. LOC | Tests | Done when |
|---|---|---:|---:|---|
| 0 | Fix the confirmed bugs. Check A's other 6 findings. Recorder triple timestamps. OVN v2 protocol; re-score H2 with correct open costs (labelled as a correction) | 300 | 12 | Fixed scorers reproduce known fixtures; amendments hashed |
| 1a | `types`, `calendar` (NSE holidays, expiries), `instruments`, `store` | 750 | 28 | Missing-session, expiry, timezone, restart fixtures replay identically |
| 1b | `costs` (fees by effective date, checked against the Upstox tariff), `ledger` | 550 | 25 | Cash, short and credit examples reconcile to the paisa |
| 1c | `risk` (limits, DG, latches) + the DG decision for the six accounts (separate replay) | 550 | 24 | Partial fills, gaps and stale marks cannot bypass caps |
| 2 | `execution` (book walk, capacity, 3 scenarios, multi-leg) + shared rate limiter | 950 | 35 | Latency, crossed quotes, depth exhaustion and wings-first covered |
| 3 | `features` + `alpha_sip` + `gs_adapter` (paper, own book) + `/gs` | 700 | 26 | Replay = live decisions; top-20 causal; every missed fill kept |
| 4 | `evaluate` + `registry` (bootstrap, power, lock) | 650 | 26 | Synthetic null, positive and dependent data give correct verdicts |
| 5 | `alpha_ovn` (₹10 L book) + range measurement | 750 | 28 | Lot feasibility, calendar exit, residual legs |
| 6 | `alpha_news` + `/gsbrief` + LLM extraction harness | 500 | 22 | Late receipts can't backdate entries |
| 7 | `allocation` + integrated stress report | 350 | 14 | All-cash and correlated-risk cases |
| **Total** | | **≈6,050** | **≈240** | Later phases are built only if earlier ones justify them |

**First useful release:** phases 0–4. That is when GS-SIP starts its 60-session pilot on paper.

**Not built:** another indicator grid, a directional LLM, reinforcement learning, market making on minute data, naked options, dispersion, basis arbitrage, an expiry-day strategy, a complex regime switcher, or live orders.

## 11. Decisions the owner needs to make before the build
1. **OVN capital:** a ₹10 L virtual book (recommended). The alternative, a 1% budget on ₹5 L, carries the same rupee risk at double the risk per trade.
2. **SIP ticket:** ₹1 L (recommended; fits the capacity measured today) or ₹3 L (fits about 28% of stock-minutes).
3. **Test lengths:** accept that a final verdict on a small edge takes years, while pilots (about 3 months) can close bad ideas early.
4. **The build command:** phases 0–4 first.
