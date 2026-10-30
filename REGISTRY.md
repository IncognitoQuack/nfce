# Pre-registered experiments

## CURRENT REGISTRATION (v3, re-registered 20 Oct 2026 after independent review round 3, before any live data)
**This section governs.** The sections after it are the original registrations of 18–20 Oct, kept for the record. Their hash tables are **superseded (historical)** and no longer match the files.

**What changed** (`evidence/review_round3_response.md`):
- **One error budget:** the four confirmatory experiments R1–R4 now share a single family-wise α = 0.05, one-sided, Bonferroni, so **0.0125 each**. R2 uses 0.00625 per index. R5 is closed, and R6 is a forecasting benchmark with descriptive, pre-declared claims (no α).
- **Day means:** every test runs on day means, one value per session (per group for R3), because trades on the same day are not independent.
- **One look:** each verdict is computed once, the first time its minimum sample is reached. There are no extensions after seeing results.
- **R1:** additionally needs ≥ 100 sessions, a positive total in net rupees, and positive net R with every option spread widened 1.5×.
  - Fills must be in time order on one session (`options_exec.py`).
  - The futures leg uses each day's front contract with bounded, same-session quotes (`registry_eval.py`).
  - The recorder keeps the eligible expiry and every strike within ±5 strikes of the session's spot range.
- **R3:** needs ≥ 40 PASS and ≥ 40 VETO trades, each group on ≥ 2 sessions. The executable book is now 10 whole lots, judges freshness at the moment of decision, and enters atomically.
- **R4:** the model is now M1, adopted by the pre-declared benchmark rule. R4 trades are independent paired shadow trials, and absolute results are reported next to the relative test.
- **R6 (new):** a live forward benchmark of the range forecasts, M1 vs the linear HAR+VIX model vs their average (`evidence/r6_protocol.md`).

| Experiment | Status | Pass rule (short) | Scorer |
|---|---|---|---|
| R1 ITM option vs futures (Nifty ORB-mid) | collecting from 21 Oct 2026 | option net ≥ +0.10R; option > 0 and option − futures > 0 at p < 0.0125 (day means); ≥ 200 trades over ≥ 100 sessions; ≤ 10% skipped; positive rupees; spread ×1.5 still > 0 | `registry_eval.py r1` |
| R2 H-A 15m ORB, futures | needs paid futures history (your decision) | as below, with p < 0.00625 per index | `registry_eval.py r2` |
| R3 option-chain veto | collecting from 21 Oct 2026 | PASS − VETO ≥ +0.20R, Welch on day means p < 0.0125, PASS > 0; ≥ 200 signals incl. ≥ 40 each | `registry_eval.py r3` |
| R4 range targets vs fixed targets | collecting from 21 Oct 2026 | mean Δ ≥ +0.05R, paired p < 0.0125 on day means, ≥ 100 pairs | `registry_eval_r4.py` |
| R5 Williams 3-day swing (NIFTY) | **FAILED, closed** | — | — |
| R6 range forecast benchmark | collecting from 21 Oct 2026 | C1–C4 in `r6_protocol.md`, judged at ≥ 600 forecasts and ≥ 40 sessions per index | `registry_eval_r6.py` |

### Frozen files (v3, SHA-256, 20 Oct 2026)
| File | SHA-256 |
|---|---|
| nfce_engine/nfce/registry.py | `3b426768d991476588198ea565b14214a217b384cbc6f7c9483c6ad6fe0ccbb5` |
| nfce_engine/nfce/registry_r4.py | `e015c3b5a709ff53ed5af58aeac095dfa0b297834cef9c0cb58fcbed0008811f` |
| nfce_engine/nfce/simple.py | `f07963875ab7838df7242e2b0c8d1eb2256bb3a920f0de90a5dc265abfe4838a` |
| nfce_engine/nfce/options_exec.py | `4105f8ca566a5aa943aa9ee00f6c2aacbc7be22aa41451696000175b8be53e64` |
| nfce_engine/nfce/costs.py (= nfce_bridge/bridge/costs.py) | `e67d013bc8f3b205eee3a7334bbfe887f10ea93685f0c62a84ed1f7b2a67096c` |
| nfce_engine/tools/registry_eval.py | `9c0ebb08c45448925551f0a1c3d7f49d4a43efcbeb4ef66946d025b29cbc4c9c` |
| nfce_engine/tools/registry_eval_r4.py | `40b7c075f53e389198507179743c40069e4b42d03151f6bcaef17916508b47c1` |
| nfce_engine/tools/registry_eval_r6.py | `0a98f4c1d3934de1b7c3ff99e484d8757e0d94cbfdd800343b42740cb1e35a72` |
| nfce_bridge/bridge/rules.py | `7f2b78f61b842eb49d741ecfd3adb5846bb37c4daf1cc035265a6c3b767250ac` |
| nfce_bridge/bridge/analytics.py | `cfd5e21976a55c188b955e3bef18b00d82025b9b9adf6e89254c29b7fa9658a6` |
| nfce_bridge/bridge/paper.py | `489e607bf247fd1d55b69b0ff88e0c87770d2c29d1b878865a9e8d1975729d58` |
| nfce_bridge/bridge/config.py | `8026a4e8ff507332f23220ab4f89754641e0d3edcf42d5e9b50e1b14999593dd` |
| nfce_bridge/bridge/service.py | `89c9578246c8591a40139981842b9cd72dbe8eaf5f99257e38e2218fe3f76fa8` |
| nfce_bridge/bridge/range_model.py | `5277fef419ac5030f395bafccc12ebd589c0f6cd04a4054a3a3cf18a30cd5889` |
| nfce_bridge/bridge/models/range_r4.pkl | `b321c77a9030d21494a071dd7a1869da2a1b7e5a2cfc510c6c7c67c10c7bb930` |
| nfce_bridge/bridge/models/range_har.json | `c89b990e2515003f0cf8b504bc627a8f1f09981262c94aa8aed3090d49c73f07` |
| evidence/r4_protocol.md | `71d71aca673ddc841a1b3d1272e4f50766ee05a192c0945e79d82b278e4b8007` |
| evidence/r6_protocol.md | `010e60b8781203e20fb1bed319c56962375439e2781971771e65575cb4ee1b0d` |
| evidence/range_benchmark_protocol.md | `a9f0afa0a3b12a09f17b859cbb4b89d8f44e2314025748bebdd11efcb5722c4a` |
| evidence/r5_protocol.md | `a0d489a49de533e6161931f87098a869ea07ea149b1b30e4ffc1720bf4a6755a` |
| evidence/external_protocol.md | `2d6d199bb196ae716642c45d33f85e9b4793fd4a81f30e1422a13266273ef2d7` |
| evidence/stock3m_protocol.md | `1adecd083510bf861df6aef7333d6e4fb2f9deb8b80706722f01a49ff52cfed3` |
| evidence/early3m_protocol.md | `a652333949eda792c221287364baed050e4b64315461fe2e94a5e5fa8b5ec5d3` |
| evidence/stock15m_protocol.md | `eacb254ee6d20d3d3fab5dad8200eafe460a7629a1277f0b9addb15df50936f5` |

**v3.1 amendment (20 Oct 2026, evening, before any live data).** `service.py`, `paper.py` and `config.py` changed, and their hashes above are the new ones. The changes:
- signals may now also come from the bridge's own engine (source `engine`), with the same rules as the TradingView strategy;
- an `options` paper book follows executable trades;
- a `scanner` book (stock futures).

**The rules and thresholds of R1–R6 are unchanged.** For R3 and R4, executable-book trades count whatever their source, TradingView or engine. The scanner and options books are descriptive, not registered tests; the scanner's rules already failed (`evidence/scanner_result.md`). Protocol `evidence/scanner_protocol.md` is SHA-256 `5d1cd15139be2e828a11e8fa469aa7ab1ee663e8e9acbbff455c28c7e71d9795`.

**v3.2 amendment (21 Oct 2026, 00:50, before any live data).** nfce_bridge/bridge/service.py, nfce_bridge/bridge/range_model.py changed:
- pre-market history download (08:45–09:15);
- the range model checks its hours before downloading (the forecasts it makes are unchanged);
- the engine waits when Upstox history lags a day.

No rule or threshold of R1–R6 changed.

**v3.3 amendment (21 Oct 2026, evening, before the next session).** nfce_bridge/bridge/paper.py, nfce_bridge/bridge/config.py, nfce_bridge/bridge/service.py changed. The changes are paper ACCOUNTS (`bridge/account.py`), the watchlist scanner, option legs for every stock signal, the spread limit, warm-up and the creator chat. Two new studies were registered before their results (`stock3m_protocol.md`, `early3m_protocol.md`; both FAILED, see `stock3m_result.md`). No rule or threshold of R1–R6 changed.

**v3.4 amendment (21 Oct 2026, evening, before the 22 Oct session).** nfce_bridge/bridge/config.py and nfce_bridge/bridge/service.py changed (new hashes above): the Telegram bot gained roles (admin / user), admin controls, plain-English questions and unattended jobs (`bridge/bot.py`); the paper account gained loss-avoidance rules (cost gate, one position per underlying, premium cap, loss-streak cooldown, premium stops). One new study was registered before its result: `stock15m_protocol.md` (hashed 17:54 IST), **FAILED** in training (`stock15m_result.md`). No rule or threshold of R1–R6 changed: the R1/R3/R4 books, their entries and exits are untouched.

**Timestamping outside this package (review L01):** a hash proves a file is unchanged, not when it was written. To fix the date independently, the owner can email this table to themselves today, or post its SHA-256 publicly.

---

# Original registrations (18–20 Oct 2026, kept for the record; superseded by v3 above)

**Why this exists:** NFCE showed no edge. The only honest way to look for one now is to fix the rules and the
pass/fail test before seeing the data, then accept the verdict.

**Rules for the registration itself:**
- **Nothing below may change once data collection starts.** The rules live in code, and the SHA-256 of each file is listed at the end. If a file's hash changes, that experiment must be re-registered with a new date, and data collected before that date does not count.
- **Every verdict is PASS, FAIL or INCONCLUSIVE.** INCONCLUSIVE means not enough clean data. It is never read as "almost passed".
- **The three experiments share one error budget:** family-wise α = 0.05, one-sided, split Bonferroni-style, so each experiment gets α = 0.0167. R2 splits its share over two indices (0.0083 each).
- **These thresholds are stricter than the independent audit proposed** (t ≥ 2.24 / 1.96), because three experiments are registered together.
- **Scoring is mechanical:** `nfce_engine/tools/registry_eval.py r1|r2|r3`, applying `nfce_engine/nfce/registry.py`.
- **A PASS is not permission to trade with real money.** It is permission to paper-trade that one rule live for 2–3 months and compare.

## R1 — Nifty ORB-mid executed through a 1-ITM option, vs futures on the same signals
*Source: improvement roadmap §4; audit §6 cost arithmetic. Hypothesis: an ITM option has lower fees per unit of index
move than futures, so it can rescue a small gross edge.*

| | |
|---|---|
| Signal | H1 ORB, stop = midpoint (`nfce/simple.py: orb(bars, "mid")`), NIFTY, 60-minute bars, unchanged since Phase 6 |
| Option leg | BUY signal: buy a call; SELL signal: buy a put. Nearest strike strictly in the money at the decision. Nearest expiry with ≥ 2 sessions left (no 0DTE). One lot. Enter at the ask, first quote ≥ 5 s after the signal bar's close. Exit at the bid at the H1 exit (the close of the bar that triggered it, capped at 15:25 IST). Dated option fees. (`nfce/options_exec.py`) |
| Futures leg | The same signals and timestamps, front future, ask in / bid out (bid in / ask out for shorts), dated futures fees |
| Unit | Net rupees divided by (underlying risk in points × lot size), i.e. R of the underlying signal |
| Data | Recorded live by the bridge: `option_quotes` (ATM ± 5 strikes, every chain refresh) and `quotes` (front future). NIFTY 60m bars for the same sessions. **No historical bid/ask data is used**; there is none available free. |
| Minimum sample | ≥ 200 executed trades (about 13 months at the Phase 6 signal rate); ≤ 10% of signals skipped for missing quotes |
| **PASS iff** | (1) option net ≥ +0.10R per trade, **and** (2) option net > 0 with one-sided p < 0.0167, **and** (3) option minus futures, paired, > 0 with one-sided p < 0.0167 |

## R2 — H-A volatility-gated 15-minute opening-range breakout, single exit, futures
*Source: independent audit §7.2, hypothesis H-A, with its own thresholds kept or tightened.*

| | |
|---|---|
| Rules | `nfce/simple.py: orb15_ha`. Range = 09:15–09:30 bar. Trade only if 0.25 × ATR14(daily, previous days) ≤ range ≤ 0.60 × ATR14 **and** the 09:15 bar's volume ≥ 1.5 × the median of the previous 20 sessions (needs real futures volume; refuses spot data). Entry: first 15m close beyond the range on a bar closing 09:45–11:15. Stop: other side of the range; skip if R < 60 NIFTY / 135 BANKNIFTY points. Exit: 2.0R target, stop, or 15:15 close. One trade a day, one lot, two orders |
| Costs | **Current (2026) schedule on every trade**, plus 1.5 NIFTY / 4.0 BANKNIFTY points round-trip friction. This is the cost of trading it from now on |
| Data | 15-minute continuous futures OHLCV, NIFTY1! and BANKNIFTY1!, ideally Jan 2021 – Oct 2026. Not available free: needs TradingView Premium (Deep Backtesting export) or a paid data vendor. **Spending money on data is your decision.** |
| Minimum sample | ≥ 250 trades per index |
| **PASS iff, on BOTH indices** | (1) net ≥ +0.12R per trade, (2) one-sided p < 0.0083, (3) profit factor ≥ 1.20, (4) positive net R in ≥ 3 calendar years that each have ≥ 30 trades |

## R3 — Option-chain veto, prospective shadow test
*Source: audit H-C. Hypothesis: the spec's ΔOI-flow + OI-wall veto separates good signals from bad ones.*

| | |
|---|---|
| Rules | Bridge v2 as shipped: `rules.evaluate` with PCR_DOI_VETO = 0.7, ATM_WINDOW = 5, live front-future basis. Vetoed signals are still booked as shadow trades |
| Book | Executable paper book (live bid/ask, delay and spread checks, daily risk gate), closed trades only; UNRESOLVED and REJECTED excluded |
| Data | Live forward paper trading with your Upstox keys, from the first day the bridge runs with this registration |
| Minimum sample | ≥ 200 closed signals including ≥ 40 vetoed |
| **PASS iff** | (1) mean net R(PASS) − mean net R(VETO) ≥ +0.20R, (2) Welch one-sided p < 0.0167, (3) mean net R(PASS) > 0. **On FAIL, delete the veto rule.** |

## What is deliberately NOT registered
- **NFCE itself, re-tuned.** The 9-factor score was tested on every dataset available, and re-tuning it on the same data would be curve-fitting.
- **Any rule built after looking at the Phase 2–7 results**, for example the BANKNIFTY 15m grid cluster.

## Frozen files (SHA-256, 18 Oct 2026) — SUPERSEDED (historical)
| File | SHA-256 |
|---|---|
| nfce_engine/nfce/registry.py | `1a4c93d7d290fde7eba45b86aaf1a71b588a8101454b020d937754d29eec8393` |
| nfce_engine/nfce/simple.py | `f07963875ab7838df7242e2b0c8d1eb2256bb3a920f0de90a5dc265abfe4838a` |
| nfce_engine/nfce/options_exec.py | `3492b14c8aba19fe39760906c96173c0112829161b880691e0429134b17fb45f` |
| nfce_engine/nfce/costs.py (= nfce_bridge/bridge/costs.py) | `e67d013bc8f3b205eee3a7334bbfe887f10ea93685f0c62a84ed1f7b2a67096c` |
| nfce_engine/tools/registry_eval.py | `11b4c22858474bcf4431af17a270a6605c83286d375e3126efa5f40070946979` |
| nfce_bridge/bridge/rules.py | `03fbbd1aa3eb7102fae9bf36d42c582ef6b7000c16c765ffa27dd52721b1567a` (re-registered 20 Oct 2026, see below) |
| nfce_bridge/bridge/analytics.py | `cfd5e21976a55c188b955e3bef18b00d82025b9b9adf6e89254c29b7fa9658a6` |
| nfce_bridge/bridge/paper.py | `88dd6980c220e6e274d334aff1a70fcebe182d9b68ccbe8a90b4da446e6b8e39` |
| nfce_bridge/bridge/config.py | `53c3e32f633fe96d76f99559544365bf389d9b301473443033a0ce284555c55d` |

Check: `shasum -a 256 <file>` (macOS) or `sha256sum <file>` (Linux).

## Amendment, 20 Oct 2026 (before any live data was collected)
`nfce_bridge/bridge/rules.py` changed only in input validation, after fuzz testing found two crashes:
- a non-finite score now counts as "no score";
- a bar timestamp that can't be converted, or falls outside the years 2000-2100, now counts as "no bar time".

The veto/boost rule itself is unchanged. R3 is therefore re-registered on 20 Oct 2026 with the new hash. No R3 data existed before this date; live paper trading starts on 21 Oct 2026.

## R4 — range-calibrated targets vs fixed targets (registered 20 Oct 2026, before any live data)
*Source: `evidence/r4_protocol.md`. The live-feasible range model passed 2025 validation (index R² 0.33, 77.3% coverage of
the 10–90% band) and a one-shot Jan–Jul 2026 final (R² 0.37, 77.9%) before this registration.*

| | |
|---|---|
| Book `r4` | opens only when the executable book opens, at the same entry with the same stop, breakeven/trail, 15:15 square-off and fills. Targets T1 = ±0.5 × median forecast 60-minute range, T2 = ±0.5 × the forecast 90% range, T3 = ±the 90% range (40/30/30) |
| Rejections | no forecast (data missing or stale, outside 09:45–14:15) or degenerate targets: recorded with the reason and excluded |
| Unit | net R using the signal's own risk (entry − stop), the same for both books |
| Minimum sample | ≥ 100 paired closed trades |
| **PASS iff** | mean(net R r4 − net R executable) ≥ +0.05R **and** one-sided paired p < 0.0125 (0.05 / 4) |
| Scoring | `python nfce_engine/tools/registry_eval_r4.py --db nfce_bridge/data/nfce.db` |

A PASS means range-sized targets beat fixed 1R/2R/3R targets on paper. It does not mean either one makes money.

| R4 frozen file (SUPERSEDED, historical) | SHA-256 |
|---|---|
| nfce_bridge/bridge/range_model.py | `d622f61adaa4ece00d40ab431a347257f8848992b644ff4a2952d587015661fb` (20 Oct: previous-close guard added before any live data) |
| nfce_bridge/bridge/models/range_r4.pkl | `413fc8eeffec28e5dd21bd954b9574bf1ab4386f9b58d72a382df4801e12561f` |
| nfce_engine/nfce/registry_r4.py | `314bef0c5243adf16bc6513569ab481847e28e7bf215bf6fa068b7ab401f89f1` |
| nfce_engine/tools/registry_eval_r4.py | `86f8c3c33431109dfaee903b151b459dd8ab146c582221a7720c8e4fa04a5129` |
| evidence/r4_protocol.md | `b0f437a8675d3ea96b6703e386b17d4a67d4ba336fd12107e434d95f0e5a2d84` |

## R5 — Williams 3-day swing breakout on NIFTY (registered 20 Oct 2026, ~02:05 IST, before its 2026 data was examined) — FAILED, CLOSED
*Source: `evidence/r5_protocol.md`. S4 NIFTY failed validation under `evidence/external_protocol.md` (2025: +0.059R, p 0.26). R5 is a separate, explicit test of that one rule, so the deviation is on the record before the fact.*

| | |
|---|---|
| Rule | `nfce/research2.py: williams_dsr`, unchanged; NIFTY spot as a futures proxy; current costs |
| Test A, one shot, Jan–Jul 2026 | **PASS iff** net R > 0, day-block 95% lower bound > 0, PF ≥ 1.15, ≥ 20 trades |
| **Result** | n 44, net +0.032R per trade but **−13.7 points per trade**, PF 1.09, lower bound −0.25 → **FAIL** |
| Test B (live forward) | **Not run.** The protocol starts B only "unless A fails clearly"; A failed on two of its four conditions and lost money in points, so R5 is closed |

| R5 frozen file (research2.py / external_run.py rows SUPERSEDED, historical) | SHA-256 |
|---|---|
| evidence/r5_protocol.md | `a0d489a49de533e6161931f87098a869ea07ea149b1b30e4ffc1720bf4a6755a` |
| evidence/external_protocol.md | `2d6d199bb196ae716642c45d33f85e9b4793fd4a81f30e1422a13266273ef2d7` |
| nfce_engine/nfce/research2.py | `b3d06d5cbd29f9a036da0fd0f8ef69f77d980ecdf9c9b1246fa7c2c165845fda` |
| nfce_engine/tools/external_run.py | `0afeefcee0abbb7fdab609b86aa9813974bffb9c308907f9072a80efef9cac0e` |

**v3.5 amendment (22 Oct 2026, evening, before the 23 Oct session).** nfce_bridge/bridge/config.py and nfce_bridge/bridge/service.py changed (new hashes above). The changes:
- five strategy paper accounts (`ACCOUNTS=NAME:capital:strategy`; `bridge/account.py`), side by side; the extra four are quiet;
- `/account` marks open positions at the live bid (a reporting bug found live);
- long admin messages go to the assistant instead of a keyword command.

**Registered before their results:**
| Protocol | SHA-256 | Result |
|---|---|---|
| `evidence/live_variants_protocol.md` | `8d94b8b992cf284f54d2ab452a7eb666dc66681bf6ae3481d36da024361eb05a` | forward test; 9 signals so far, no conclusion |
| `evidence/cap_replay_protocol.md` | `feb8d1b9856c05bde77e7dfa4c531bff6de61e787b107e8348fc24ec9020b320` | **FAILED** (`cap_replay_result.md`) |
| `evidence/strategy_accounts_protocol.md` | `6714a064828c45faa1786e308a21a2d5668a8687d5ca8cd672fcfb619c9b0ee1` | live from 23 Oct; judged at 20 sessions |
| `evidence/leads_2day_protocol.md` | `10cc3f993849d56ccd620bfee3520cbc3d006d93576288fcabb8cb940ade616d` | H1 and H2 **FAILED** (`leads_2day_result.md`) |
| `evidence/best_practice_tests_protocol.md` | `016cf9a434e9432c5d1d404e596e18e9a6a4a7678cbe667746e36c7dd8f0f0ae` | H3, H4 **FAILED** (`best_practice_tests_result.md`) |
| `evidence/wide_stop_protocol.md` | `21912f803a8ecc660de5c0ac46aa422f347e1166b07e5d0d49e5907ed2c19283` | K2/K3/K4 **FAILED** at train; loss falls −0.270 → −0.034R (`wide_stop_result.md`) |
| `evidence/strategy_accounts_amendment_1.md` | `de59f49571a08cf1902d6f63e9fb147b33dfc201aed496c8bb31ea5187a96c16` | adds WID4 (4× stops via options) before any trade |
| `evidence/tsmom_protocol.md` | `030dfa7ccb432bc49381a4a9301eb1b23f3f2ca595c049c21dacdb23b36de0c2` | TS250 passed train, **FAILED** 2025 validation (−5.2%); TS60/TS120 failed train (`tsmom_result.md`) |
| `evidence/profit_lock_protocol.md` | `a572115cd071a32a0ee137b752a5b646b611bb659fb21bbe06b1b14f142fe1d6` | P1, P2 **FAILED** at train (worse than no lock) (`profit_lock_result.md`) |
| `evidence/results_days_protocol.md` | `b660c95b23eaed4f858ebc28bed123b2bd6ca0f96075fd89e5c4d76e0dd2370e` | H_R **fails** (results-window signals did not do worse): flag only, no skip (`results_days_result.md`) |
| `evidence/results_k4_protocol.md` | `59dd10e46f1a83b1fdb1a9b6d1fbfffa0e5e0f95194c4cb623c8090012a6c272` | **FAILED** 2025 (−0.021R, CI includes 0); lead closed (`results_days_result.md`) |
| `evidence/gap_protocol.md` | `29ee920ede88b2968eb32ea8c167de964a1f9f9cad01aa7221edd1e86cc9dd85` | G1, G2-V0, G2-K4 **FAILED** (`gap_result.md`): the opening gap (GIFT Nifty's information) adds no edge |
| `evidence/day_rules_protocol.md` | `0f9c6573d4643e1a925b8d50144fcb3a85ebfe315bb8b91d53e41f3dc26ce7a3` | DG × V0 and DT × V0 **risk control only** on train and 2025 (losses cut, still negative); DT/DG × K4 failed (`day_rules_result.md`) |
| `evidence/xs_protocol.md` | `79239261730c9b0650fba417d363b548973e1c0879aa59727731012e3db5d5f2` | XM, XR **FAILED** train (XM closest: +0.52%/mo, p 0.066); ON passed train, **FAILED** 2025 (−10.6%) (`xs_result.md`) |
| `evidence/xm_old_protocol.md` | `6cf083967bd4f1e801e298708ae272654cc7becda400bf5109d7cd0451868bb7` | **FAILED** on 2007–16 (−0.20%/mo; gross +0.003%); XM closed. A calendar bug was found and fixed; the earlier tests were re-run with verdicts unchanged (`xm_old_result.md`) |
| `evidence/meta_label_protocol.md` | `d733482202f3bcdda9f32f67378a2a5a53070ade3d0e208b18632e01186c30f7` | **FAILED** at 2025 validation (`best_practice_tests_result.md`) |
| `evidence/study_engine_protocol.md` | `038e4dfe21c492df9bbe2f3b3f494db857bfdc3f9a9fa2a632e486e35f704862` | registered 26 Oct 2026 10:36 IST, before any run. 2,232 rules: 23 train candidates, **0 passed 2024 validation**, final not run (SPA p 0.12 train / 0.60 val) (`study_engine_result.md`) |
| `evidence/study2_protocol.md` | `98291e82aacfc8325b4203635aa4a2a0ac2f8b3d3c3a6a2d4a84e67208e872bc` | registered 26 Oct 2026 10:57 IST, before any run; 8 literature hypotheses, order-book costs. 7 failed the 2022–24 gate; H7 (v1 gap-fade lead) **FAILED** the one-shot 2025–26 final (+0.121R/trade but p(day) 0.98: a few panic days) (`study2_result.md`) |
| `evidence/overnight_options_protocol.md` | `30f95dab5f7e8cfe1b92a8add29d6a917eed5082af6a5e15aaa1f9e0b55f0a64` | registered 26 Oct 2026 11:35 IST, before the first entry (15:20). Forward paper test: NIFTY ATM iron fly / 1-SD iron condor, 15:20 → next 09:16, from the recorded chains; judged at 40 entered sessions |
| `evidence/range_vs_implied_protocol.md` | `f1852aa46309f9d9182a2c96602eab56164845e2f6aa1971cd7e7302eac469f9` | registered 26 Oct 2026 ~11:40 IST. Forward measurement (no trades): range model vs the ATM-straddle implied move, claims C1–C3; from 27 Oct; judged at ≥ 20 sessions and ≥ 250 forecasts per index; 26 Oct = pilot |
| `evidence/news_reaction_protocol.md` | `4cc397fa433f6417ba3681fb377aea59c1ad196264beaea4113c109aeb4b6dc0` | registered 26 Oct 2026 11:41 IST. Forward: F&O stock reaction to in-hours NSE announcements (A, descriptive) + rule R1 (follow a ≥ 0.40% 5-minute abnormal move, exit at +60 min); judged at ≥ 100 trades and ≥ 30 sessions from 27 Oct; 26 Oct = pilot |
| `evidence/overnight_options_v2_protocol.md` | `18fce1fad36b1f2f46dab972df6a5ca3eee4330d20648ffdc933a76c9810de68` | registered 26 Oct 2026 13:54 IST, before the first entry (15:20). **v2 of the overnight test = GS-OVN-1** (₹10 L book, 0.5% budget): calendar next session, no LTP marks (unresolved instead), separate exit-fee reserve, wings 1×ATR14. Pilot 60 / validation 60 / final N; **v1 superseded, its judgement withdrawn** |
| `evidence/gs_phase0_amendments.md` | `aa85e198c9a8dae6f84adef410f16531f7b22a71823500be99c1060a94bda455` | 26 Oct 2026 14:00 IST. Review A's findings checked: 1, 3–9, 11 real; 2 real but immaterial (0 regular sessions dropped); 10 a caution. Amends `range_vs_implied` (calendar holidays) and `news_reaction` (causal R1 entry, bounded NIFTY quote ages) before their first judged session (27 Oct). H1–H3 re-scored with the open-entry cost: H2 −3.5 bp/trade, still FAIL (`study2_result.md`) |
| `evidence/gs_sip_1_development_protocol.md` | `8e590ffe6b33132188c5bbdf488b3fe735d5c443b755b6e4af438c55b26c2077` | registered 26 Oct 2026 16:48 IST, before any historical GS-SIP-1 number was computed: the bar translation of GS-SIP-1, the seeded random sample, and at most 3 pre-declared single changes (stop 1.0 ATR, RVOL >= 2, window to 10:30) with a select-on-2022–24, check-once-on-2025–26 rule. Development only; never counts toward the forward test (`gs_sip_1_development.md`) |
| `evidence/gs_sip_1_protocol.md` | `5666105150c58d834bb8dce3ce12ea6cb3ffbfd13be1ca6423fb4d64ac6a4fa1` | **GS-SIP-1 REGISTERED** 26 Oct 2026 16:59 IST, before its first session (27 Oct). Manifest `216728d1b2b44b4469bc10beb1c4ec331d0e323edf3c8de3bf172013802c1e50` (sha256 of the canonical JSON in `evidence/gs_sip_1_manifest.json`; frozen in `nfce_bridge/data/gs.db`). Forward paper test: pilot 60 / validation 60 / final N, α 0.003125; as-designed rules (no historical candidate qualified); history (development) lost money after costs, so the pilot's futility stop may close it |

**No rule or threshold of R1–R6 changed:** the executable, r4 and options books, their entries and exits are untouched.

**v3.6 amendment (23 Oct 2026, evening, before the 26 Oct session).** nfce_bridge/bridge/service.py changed (new hash above). The only change is two helpers for the 📰 results flag: `_refresh_results`, called from `premarket`, and `results_flag`, used by the stock and scanner alerts (`bridge/events.py`). No book entry, exit or scoring rule changed. Outside the frozen files, `bridge/account.py` gained the true-breakeven correction (CHANGELOG v3.6). It is an account rule, not an R1–R6 rule. **No rule or threshold of R1–R6 changed.**
Later the same evening, nfce_bridge/bridge/config.py also changed (new hash above): `SCANNER_MODE` accepts `sell`. The scanner book is descriptive, not a registered test. **No rule or threshold of R1–R6 changed.**

**Correction (23 Oct 2026, evening).** Earlier hash updates had been made with a whole-file find-and-replace. They also overwrote two rows of the *superseded* 18 Oct table: paper.py and config.py. Both rows are restored to their original values (`88dd6980…`, `53c3e32f…`), taken from earlier copies of this file in the package history. From now on, hash updates touch the current table only.

**Amendment: overnight test v2 (26 Oct 2026, 13:54 IST, before the first entry at 15:20).** `evidence/overnight_options_protocol.md` (v1) is superseded by `evidence/overnight_options_v2_protocol.md` before any v1 entry was made; v1's row above is kept as it was, and its judgement is withdrawn. Why: review A found, and the code confirmed, that v1 paired consecutive data files instead of exchange sessions, marked missing legs at the last traded price, split fees half-and-half into "entry fees", and set wings from an uncalibrated IV-based overnight SD. The v1 code path (`overnight_options.py score`) is unchanged and reproducible. Frozen with v2:

| OVN v2 frozen file | SHA-256 |
|---|---|
| evidence/overnight_options_v2_protocol.md | `18fce1fad36b1f2f46dab972df6a5ca3eee4330d20648ffdc933a76c9810de68` |
| nfce_engine/tools/overnight_options.py | `8fd982c95c44614e214670fadb301af1510a42269c1572ca3c4d15b09369889a` |
| nfce_engine/gs/calendar.py | `31c205d08c5d367e04a940fc183d2beeee462cc71bb8f25d230a7e80a2ad5df2` |
| nfce_engine/gs/costs.py | `4bced892127e5a518543f40639e02df8c6601a5a673e92c753b327bcc7a94bbd` |
| nfce_engine/gs/instruments.py | `b199f29023581f5297c9517fb602311426c49ae1d99a9dd5cd1605c05970d774` |
| nfce_engine/tests/test_overnight_v2.py | `48eb761279a89079e7aa93f89b4c8a49bee94737eb0b24dd7d905a0ef7f49272` |
| nfce_engine/nfce/costs.py (unchanged, wrapped) | `e67d013bc8f3b205eee3a7334bbfe887f10ea93685f0c62a84ed1f7b2a67096c` |

If a later GS phase edits `gs/calendar.py`, `gs/costs.py` or `gs/instruments.py`, a new row records the new hash, and `tests/test_overnight_v2.py` must pass unchanged (the v2 behaviour may not move).

**Amendment: GS phase 0 corrections (26 Oct 2026, 14:00 IST).** Record: `evidence/gs_phase0_amendments.md`. Each correction is behind a flag whose old value reproduces the registered behaviour. No verdict changes.

| GS phase 0 file | SHA-256 |
|---|---|
| evidence/gs_phase0_amendments.md | `aa85e198c9a8dae6f84adef410f16531f7b22a71823500be99c1060a94bda455` |
| nfce_engine/tools/news_reaction.py (`CAUSAL_FIX`) | `f96ce859335e51b4d39b40bd9a5b964c70fa23b18a3bb2fb4c0ca645a9d520bf` |
| nfce_engine/tools/range_vs_implied.py (`HOLIDAY_FIX`) | `3cc586a01b98b0ed792effaeb70657cc76d62bf6a69c67113567153abf2a23a0` |
| nfce_engine/tools/study2.py (`ORB_OPEN_COST_FIX`) | `bf5c33e36cd7efb88dce4d89dd35479bb7983300a5a5b5aa7291a4b353f23cab` |
| nfce_engine/tools/study2_rescore.py | `881d24e0fc1e511efe6488fc0b4ea950acc89c584946279d6280659d6e6fa681` |
| nfce_engine/tools/gs_phase0_checks.py | `fec96ee608a43c690ffeefb710083a8fdb93821b4bd904105f7366e70fe8021e` |

**OVN v2 amendment 1 (26 Oct 2026, 14:28 IST, before the first entry at 15:20).** `nfce_engine/tools/overnight_options.py` → `2a9d6aeb7eeaa21c011bcdf339ed8238bf4ee6ccf5164ad089b18f744ba2c866` (was `8fd982c9…889a`). The only change: the `stress2` diagnostic crashed on the calendar's first night (3 Jan 2022, whose previous session is outside the calendar); it now skips such nights. `score_v2` (the scorer) is byte-for-byte the same logic; `tests/test_overnight_v2.py` passes unchanged. Diagnostic result (not a pass condition): 1,182 nights 2022–26; the open gapped ≥ 1 previous-day ATR14 (the wing) on **3.9%** of nights and ≥ 0.5 ATR on 20.9%; worst 4 Apr 2025 −4.5 ATR, 2 Feb 2026 +4.2 ATR (after the Sunday Budget session), 31 May 2024 → 3 Jun +3.5 ATR (election exit polls).



**v3.7 note (26 Oct 2026, after the close, before the 27 Oct session).** Outside the frozen files: `bridge/account.py` gains the give-back stop (DG) in all six paper accounts (decision and live replay in CHANGELOG v3.7; evidence `evidence/day_rules_result.md`). `bridge/telegram.py` (muted chats get no replies) and `bridge/scanner.py` (surge wording) change messages only. DG is an account risk rule, applied to all six so the strategy-account comparison stays fair; the accounts' 20-session judgement continues. **No rule or threshold of R1–R6 changed, and no frozen file changed.**

**v3.7 GS amendment (26 Oct 2026, after the close, before the 27 Oct session).** nfce_bridge/bridge/config.py and nfce_bridge/bridge/service.py changed (new hashes above; were `cc8caa18…c92d` and `2a5d35c7…594b`). The changes wire the GS research engine (`GS_ENGINE_FINAL_BLUEPRINT.md`) into the bridge, **off by default**: `config.py` adds `GS` (default off) and `GS_DB`; `service.py` creates `bridge/gs_live.py`'s `GSLive` only when `GS=on` (and the stock engine is on), starts its own 2 s thread from `tick` inside `_safe`, and adds an informational GS line to `/health`. Outside the frozen files: `bridge/gs_live.py` (new), `bridge/gs_adapter.py` (docstring), `bridge/bot.py` (read-only admin `/gs`, `/toggle gs`). GS runs in its own book and database (`data/gs.db`), never touches the six accounts, nfce.db or any R1–R6 book; GS-SIP-1 remains DESIGN until its manifest is frozen. **No rule or threshold of R1–R6 changed.**

**GS-SIP-1 registration (26 Oct 2026, 16:59 IST, before the 27 Oct session).** `evidence/gs_sip_1_protocol.md` (status REGISTERED) and its manifest (`evidence/gs_sip_1_manifest.json`, sha256 of the canonical JSON `216728d1…1e50`) are frozen; the manifest is stored once in `nfce_bridge/data/gs.db` (append-only; a second freeze under the same id is refused). It pins the code (`nfce_engine/gs/*.py`, `bridge/gs_adapter.py`, `bridge/gs_live.py`, `nfce/costs.py`), this protocol, the fees, the calendar and the dependency lock (python 3.14.4, numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1). `bridge/gs_live.py` checks it every morning and does not run GS on any difference; the only allowed change is a calendar extension that adds later dates (the 2027 holidays), recorded with `gs.registry.register_calendar_extension` and a row here. The historical development test is `evidence/gs_sip_1_development.md`; it never counts toward this test. GS runs only with `GS=on` in `.env`. **No rule or threshold of R1–R6 changed; no frozen file changed.**



**GS-SIP-1 re-freeze (27 Oct 2026, ~09:05 IST, before any GS decision).** At 09:00 on 27 Oct, GS sat its first day out: "freeze check failed: ProgrammingError". `gs/store.py` opened its SQLite connection on the bridge's main thread, and GS steps on its own thread, so sqlite3's same-thread check failed every call. The tests had never crossed threads. Fix: `check_same_thread=False`, with the test `test_store_made_on_one_thread_works_on_another` (engine 306, bridge 234). No rule, parameter or protocol text changed: `evidence/gs_sip_1_protocol.md` keeps sha `5666105150c58d834bb8dce3ce12ea6cb3ffbfd13be1ca6423fb4d64ac6a4fa1`. The empty pre-fix store (1 freeze record, 0 events) was moved to `data/backups/gs_prefreeze1_20261027.db`, and the manifest was re-frozen as **`ce4f89c97fc2598172d9369a38807274a93fab78536f945cdf657adeff3dc590`** (`evidence/gs_sip_1_manifest_v2.json`). The freeze tool refuses a start on a session already under way, so **the counted start moves to 28 Oct 2026**. 27 Oct runs on the frozen code as an uncounted day. The earlier manifest `216728d1…1e50` is superseded; it never ran a session.

**NFCE-X and research tests, 27 Oct 2026 (each protocol hashed before its run; the live system was not changed).**

| Protocol | SHA-256 | Registered | Result |
|---|---|---|---|
| `evidence/reversed_signals_protocol.md` | `5e28c28db685c5a55e19543e95d83f3949006bea91d74d367793e5a3551fbd68` | 14:39 | **FAIL** at train: reversed −0.374R vs as-given −0.270R (16,598 trades). `reversed_signals_result.md` |
| `evidence/ovr_reversal_protocol.md` (OVR-1) | `23f54111ee8eb7278f5c32b9029cf42e999e335f5940cbc8ebedc0e3daa6b8f7` | 14:41 | **FAIL** at train: 365 trades, net −14.4 bp. `ovr_reversal_result.md` |
| `evidence/nfx_model_protocol.md` (M1) | `fc66f7892dcc59ce57ee247e3849205751e7dd2e72f1edbad60fd0e13c955881` | 14:40 | Train walk-forward +15.7 / +10.7 / +3.4 bp, but a bid-ask bounce artifact (entry +15 min: all negative). Validation NOT run. `nfx_model_train_result.md` |
| `evidence/nfx_model_amendment_1.md` (M1-A1, executable entry) | `58db352c996156d9c87452d002822c9784a36fb8675e1d11e4f692392e83a66b` | 15:36 | Train −13.9 / −6.1 / +21.1 bp (CI spans 0): not clearly positive, so validation NOT run. `nfx_model_amendment_1_result.md` |

The 2025 and 2026 data remain unused by any NFCE-X model. GS-SIP-1 still verifies FROZEN (manifest `ce4f89c97fc2`) after these additions: the new files are outside its manifest, and no dependency was installed.

**OPX-1: range-gated overnight NIFTY iron fly (forward paper pilot), registered 27 Oct 2026 after the close, before any covered outcome existed.**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/opx_1_protocol.md` | `93c3dd746fa20f4e50e73ff8f02880b091b34fad2b8f163e030eb22ce2088386` | 16:24 | Pilot: 60 sessions from 27 Oct. Uses OVN v2 unchanged, plus a gate: ATM IV ≥ 1.50 × ENS forecast volatility. One GS claim slot (α 0.003125) at the final |
| `evidence/opx_1_amendment_1.md` | `395309f5875da7f896f11c50c4511704bdeeb61a78ddcbc859947524b5cd87a8` | 16:28 | Clarification: the gate is n/a when OVN v2 forms no structure (coverage follows OVN v2) |

27 Oct: OVN v2 skipped (VIX gate), so the OPX-1 gate is n/a. Scorer `nfce_engine/tools/opx_gate.py` (imports `overnight_options.py`, unchanged); tests `tests/test_opx_gate.py` (6).

**OVN v3: the overnight iron fly centred on the put-call-parity forward, a NEW sample alongside v2 (owner-approved 27 Oct 2026), registered after the close, before its first session (28 Oct).**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/overnight_options_v3_protocol.md` | `41e4449d2ae8813bced21d142b428ad81eb11d802e336e9f620034e8ac154ff6` | 16:31 | v2 verbatim except rule 7: K = the strike nearest the parity forward F (the median of k + mid C − mid P over the 3 strikes nearest the chain spot). Own pilot / validation / final from 28 Oct; own GS claim slot |

Scorer `nfce_engine/tools/overnight_v3.py` (imports the frozen `overnight_options.py`, which is unchanged); tests `tests/test_overnight_v3.py` (4). Descriptive check on 27 Oct 15:20 (before v3's start): the 3 Nov forward was 22,784.8 vs the frozen chain spot 22,760.75, giving K 22800 (v3) vs 22750 (v2).

**SCALP-1: order-book-imbalance scalping, passive entries (forward paper test on stream ticks), registered 27 Oct 2026 after the close, before its first session (28 Oct).**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/scalp_1_protocol.md` | `96f1bdd369b83eb991fe9578a5a9e25d83e0f09800efd5cb097ceb9058b57803` | 16:41 | Pilot 10 sessions (futility), then 30, then a frozen 30-session validation. One configuration. **Prior written before data: FAIL** |

Simulator `nfce_engine/tools/scalp_sim.py` (tests `tests/test_scalp_sim.py`, 7). Exploratory pre-read after the lock (`evidence/scalp_1_preread.md`): the signal moves the next-minute mid +0.65 bp in its direction (53.4% hit, 26,149 signals, 4 days) vs 4.53 bp fees at a ₹5 L ticket.


**SH-1: "book small profits, hold losers to recover" (the owner's live rule, SHADOW only), registered 28 Oct 2026, 10:43, before any of that day's positions closed.**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/shadow_hold_1_protocol.md` | `21dca3dd7cefe66042694cfe601fbd68017f610e116a89d5331f7ccd5de28962` | 10:43 | Shadow replay on the stream's option ticks (`nfce_bridge/ops/shadow_hold.py`). 28 Oct, 11 clean positions: SH-1 −₹15,705 vs the accounts −₹3,380. Not adopted |

**SMART-EXIT-1: early profit booking / smarter loss handling on the stock 3m signals (5 variants, Bonferroni), registered 28 Oct 2026, 13:37, before any run.**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/smart_exit_1_protocol.md` | `b62e3b9705a91ff1cf95755c7916a75cf8e2e66b53360cfe20f97e4a55d46adc` | 13:37 | **Train 2022–24: all five FAIL** (`evidence/smart_exit_1_result.md`): S1 −0.307R, S2 −0.322R, S3 −0.284R, S4 −0.306R, S5 −0.334R (worst day −70R) vs LIVE −0.250R. Validation and final not run; not re-tuned |

Walker `nfce_engine/tools/smart_exit.py`; tests `tests/test_smart_exit.py` (4).


**SMART-EXIT-2: the owner's tight-stop rule ("book a decent profit, exit the moment it touches a small loss"), 4 variants, registered 28 Oct 2026, 17:12, before the run.**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/smart_exit_2_protocol.md` | `9fe876ea0b911df5b1a1fc577bed00dd9417c1f893c6cfa2fb45c1bcfe0947a0` | 17:12 | **Train 2022–24: all four FAIL** (`evidence/smart_exit_2_result.md`): T1 −0.335R, T2 −0.352R, T3 −0.335R, T4 −0.339R; negative even before costs. Not re-tuned |

**G20 "guarded" paper account (₹20 L), registered 28 Oct 2026, 17:24, before its first session (29 Oct).**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/guarded_account_protocol.md` | `643e2ebd1fc4710986ae304fe3984d8831dce168e3796267729f667af274ae98` | 17:24 | Base + 30-min time stop + 15% cost gate + no index entry without a fresh futures quote. **Risk controls, not a measured edge.** Verdict after 20 sessions; one day is not evidence |


**CAL-1: turn-of-the-month and pre-holiday long NIFTY futures (published calendar effects), registered 28 Oct 2026, 21:15, before any result.**

| Protocol | SHA-256 | Registered | Status |
|---|---|---|---|
| `evidence/cal_1_protocol.md` | `2e2271321a492c885d2cac13dfbd3e19dd1050201c0325d48c2b3b23bcb60079` | 21:15 | **Train 2006–2015: both FAIL, narrowly** (`evidence/cal_1_result.md`): C1 TOM +48.4 bp/trade net, CI −10.4..+106.6, p 0.053; C2 pre-holiday +19.1 bp, CI −5.8..+44.0, p 0.068. Validation and final NOT run (per protocol); not re-tuned |
