# GS-SIP-1: stocks in play, cash equity, passive entry: forward paper test

**Status: REGISTERED** (26 Oct 2026, evening, before the 27 Oct session). Written as a design earlier the same day (GS phase 4); the owner then asked (via the main session, ~16:10) that GS "count" from 27 Oct. The rules below are the as-designed rules: none of the three pre-declared historical candidates qualified (`gs_sip_1_development_protocol.md`, SHA `8e590ffe…2077`; results `gs_sip_1_development.md`). The wiring (`nfce_bridge/bridge/gs_live.py`, off unless `GS=on`), the recorder timestamps (phase 0c) and the manifest freeze (`tools/gs_manifest.py --freeze`, stored in `nfce_bridge/data/gs.db`) are done; the REGISTRY row carries this file's SHA-256 and the manifest's.
**Start rule: the first session is Tuesday 27 Oct 2026.** The 60-session pilot then runs to about late January 2027 (exchange calendar).
**What history says (development data, not evidence):** on 2022–26 3-minute bars the rule lost money after costs (strict passive −2.0 bp/day of ₹5 L, 95% CI −3.8 … −0.2; market entries −3.7 bp/day): a small gross edge (+5 to +7 bp per trade) against about 16 bp of costs per trade at the sizes the risk rule allows, of which the fixed ₹40 brokerage is the largest part. **Expect the pilot's futility stop to close it** unless live passive fills are much better than the bar proxy. It is run because it is paper and because only live quotes can measure passive fills.
**Source:** `GS_ENGINE_FINAL_BLUEPRINT.md` section 5 (approved by the owner 26 Oct 2026: ₹1 L ticket, pilot 60 / validation 60 / final N from the power calculation), with A (`~/Downloads/GS_engine_blueprint.md`) sections 4–6 and 10.
**Code:** `nfce_engine/gs/alpha_sip.py` (rules), `gs/execution.py` (fills), `gs/risk.py`, `gs/ledger.py`, `gs/costs.py`, `gs/features.py`, `gs/calendar.py`, `gs/evaluate.py`, `gs/registry.py`; tests `nfce_engine/tests/test_gs_*.py`.

## Hypothesis
Institutionally driven repricing after stock-specific news continues beyond the opening range, because large orders are worked through the day. **Plain claim tested:** the strategy's mean daily net P&L, on fixed virtual equity, is above zero after all fees and spreads, under the strict passive-fill model.
**What is already known (development data, not evidence for this rule):** study engine v2's H2 (the same idea, market orders, entries from 09:21) made about +10 bp gross per trade in 2022–24 and **−3.5 bp net** after the corrected open-entry cost (`study2_result.md`, Correction). A post-hoc split of H2 by entry time (entries from 09:30: +17.5 bp gross, +5.0 bp net) is a subgroup of a failed hypothesis and is not evidence. **No profit is forecast.**

## The book
- Its own virtual book **E0 = ₹5,00,000**, separate from the six accounts. Paper only; no order code exists.
- **Fees** (`gs/costs.py`): STT 0.025% on sales, NSE 0.00322% each side, SEBI ₹10/crore, stamp 0.003% on buys, **₹20 brokerage per order**, GST 18% on brokerage + exchange + SEBI. At a ₹1 L ticket the round-trip fees alone are **≈ 8.3 bp** (the ₹40 brokerage is 4 bp). Brokerage is checked against Upstox's official tariff page before the freeze (₹20 flat and "₹20 or 0.1%, lower" give the same fee at ₹1 L).

## Rules (all in `gs/alpha_sip.py`)
1. **Universe:** that morning's F&O cash stocks with a recorded quote stream.
2. **Selection at 09:21** (decided at the first event after 09:21:30, because the bridge receives the 09:18 bar's last minute about 15–20 s after 09:21; a stock whose 09:18 bar has not arrived by then is ineligible):
   - both 3-minute bars 09:15 and 09:18 complete; valid opening windows (09:15–09:21 volume > 0) on **each of the 14 previous exchange sessions**;
   - `RVOL = (09:15–09:21 volume) / mean of the same window over those 14 sessions`, **≥ 1**;
   - **ATR14** (Wilder, over the 100 previous completed sessions, seeded with the mean of the first 14 true ranges) / previous close **≥ 1%**;
   - keep the **top 20 by RVOL** (ties by instrument id), ranked before any breakout is looked at;
   - direction = sign(09:21 close − 09:15 open); 0 = skip. Boundary = the opening-range high (long) or low (short).
3. **Trigger:** the first completed 3-minute bar **starting at or after 09:30 and closing by 11:30** whose close is beyond the boundary. One per stock per day.
4. **Decision:** at the first quote of that stock received at or after the bar's availability, within 10 s (otherwise the opportunity is *skipped: no book refresh*, and scores zero).
5. **Entry (branch P, primary):** a limit at **min(boundary, bid)** for a long or **max(boundary, ask)** for a short, rounded against aggressiveness to the tick; active **2 s** after the decision; expires **180 s** after the decision or at **11:33**, whichever is first. No chasing, no replacement, no second attempt. Partial fills keep the filled quantity; the rest expires.
6. **Branch M (counterfactual, a diagnostic only):** the same signals and sizes, marketable after the same 2 s, walking the displayed book (within 10 s of activation, else unfilled). M replaces the separate H2 market-order account brief. It is never a route to a pass.
7. **Exit:** stop at the average fill − / + **0.5 × ATR14**; when a quote's bid (long) or ask (short) reaches the stop, the position is closed at the next valid quote at least 2 s later, walking the book (a gap gives the worse price). Otherwise out at the first quote from **15:15**, at the touch. No target, no breakeven, no trailing. The unfilled rest of an entry order is cancelled when the stop is hit.
8. **Size:** risk **0.25% of current equity × regime** per trade, with stress loss per share L = 0.5 ATR + 0.25 ATR + half the spread + fees per share (fees re-evaluated at each quantity); **ticket ≤ ₹1 L**; **capacity ≤ 5% of the trailing 5-minute average traded value per minute**; the section 7 caps (gross ≤ 100% of equity, |net| ≤ 50%, one stock ≤ 20%, one sector ≤ 30%, **at most 4 open**, cash stress ≤ 1%, clusters (same sector or correlation ≥ 0.7) ≤ 0.5%). Pending orders count at their full requested size; a position without a valid mark blocks new entries. If a cap binds, a partial size; below one share, skip. **Inactive in v1, stated:** the instrument data has no sector field and no correlation history is kept live, so the 30% sector cap and the clusters reduce to per-stock caps; every other cap is active.
9. **Regime and latches** (`gs/risk.py`): previous-close VIX ≤ 20 full size; (20, 25] half; > 25 or up > 20% in 5 sessions a quarter; unknown VIX = no entry. DG latch for this book (r0 = 0.25% of start-of-day equity; once the day's realized net peak H ≥ 2 r0 and the day's realized net ≤ 0.5 H, no new entries that day). Day loss ≥ 1.5% of start-day equity (marks included): no new entries that day. Drawdown ≥ 5% from the running high: paused until a review starts a new paper epoch.
10. **Events** (blueprint section 7): no entries on a Union Budget day; none with a decision 09:30–10:30 on an RBI policy day (dates in `gs/calendar.py`).
11. **Fees per fill, brokerage per order:** a passive order filled in several parts pays its ₹20 brokerage once (on the first part).
12. **Diagnostics recorded at every decision, never acted on in v1:** top-of-book imbalance, ER20 trend/chop label, markouts at 10 s, 1 min and 5 min after each fill.

## Data and timing (blueprint section 4)
- Quotes and bars carry the time our process received them; the recorders store request start, response received and the exchange time when given. A decision uses quotes ≤ 2 s old; replay feeds events in availability order, and the same engine functions run live (adapter) and in replay (a test checks byte-identical intents and fills).
- Missing data never disappears: an open position without a valid quote stays *unresolved*, with a worst bound (its stress loss) and a best bound; days without data count against coverage.
- The shared request budget (`gs/budget.py`, ≤ 1,600 per 30 min) applies once the adapter is wired; an HTTP 429 freezes new entries.

## Series and scenarios
- **Primary daily series:** the day's net ₹ of all opportunities (unfilled = 0) under **strict** passive fills, divided by E0, in bp. Every exchange session is a row (zero-trade days are zeros).
- **Strict-through:** after activation a later ask is at least one tick below the buy limit (bid above the sell limit); fill **at the limit**, at most 10% of the visible size at that quote; partial fills accumulate until expiry.
- **Adverse stress:** from the strict outcomes, the best 25% of filled trades are set to zero and the rest pay 2 bp of notional (ex post, never a filter).
- **Touch:** optimistic, an illustration only; it can never support a pass.
- **Widened:** every marketable fill's distance from the mid × 1.5.
- **Reported every week, labelled "not yet evidence":** opportunities, fill and partial-fill rates, delays, markouts, fees, the M counterfactual, the missed winners (M wins that P did not fill), plain daily P&L.

## Stages and judgement (`gs/evaluate.py`, `gs/registry.py`)
Inference: stationary block bootstrap on the daily series, expected block 5, 50,000 replicates, seed 20261026, null-centred one-sided test; fixed-block (circular) bootstraps with blocks 10 and 20 as extra hurdles. Each stage is recorded once, in order, under the frozen manifest hash; a changed manifest or a second look is refused by the code.
1. **Pilot: the first 60 exchange sessions from 27 Oct 2026.** Data quality, fills, fees, capacity and the SD of the daily series. **Futility:** if the 90% upper bound of the mean strict series (unresolved at their best bound) is below zero → **FAIL**, closed. Otherwise the final length is fixed: `N = ceil(1.5 × ((2.734 + 0.842) × σ / 1 bp)²)` with σ = the pilot SD in bp (planning value 1,000). If N cannot be completed within 5 calendar years (≈ 1,240 sessions): **INFEASIBLE**.
2. **Validation: the next 60 sessions**, rules frozen. Continue only if total net ₹ > 0 (unresolved at worst), total widened > 0, coverage ≥ 95% and ≥ 100 filled trades; fewer trades → INFEASIBLE, otherwise FAIL.
3. **Final: the next N sessions, one look, α = 0.003125** (one of the 16 GS claim slots). **PASS** needs all of:
   - p < 0.003125 at block 5 and at fixed blocks 10 and 20; the 99.6875% lower bound > 0;
   - mean ≥ **1 bp/day** of E0; total net ₹ > 0; widened total > 0; **adverse-stress mean > 0**;
   - ≥ 500 filled trades on ≥ 100 distinct days; coverage ≥ 95%;
   - no unresolved execution-validity gate, and no unresolved exposure that could flip the verdict (else INCONCLUSIVE).
   A pass is labelled **"conditional on the passive fill model"**: minute and top-of-book data cannot prove queue position, and an inability to validate passive execution bars any deployment even after a pass.
- **Verdicts:** PASS / FAIL / INCONCLUSIVE / INFEASIBLE. No extension after seeing results; any rule change is GS-SIP-2 with a new sample. A result that depends on touch fills closes this version.

## Manifest (A section 16; frozen with `gs/registry.freeze`)
```text
id = GS-SIP-1
status = FROZEN
blueprint_sha256 = sha256(GS_ENGINE_FINAL_BLUEPRINT.md) at the freeze
protocol_sha256 = sha256(this file)
code_hashes = nfce_engine/gs/*.py, nfce_bridge/bridge/gs_adapter.py, nfce_bridge/bridge/gs_live.py, nfce_engine/nfce/costs.py
dependency_lock_hash = gs.registry.dependency_lock() (python, numpy 2.5.4, pandas 3.0.6, scikit-learn 1.9.1)
calendar_sha256 = sha256(gs/calendar.py); fee_sha256 = sha256(gs/costs.py) + sha256(nfce/costs.py)
start_rule = first session 27 Oct 2026 (start_session = 2026-10-27)
pilot_sessions = 60; validation_sessions = 60; final_sessions = N from the pilot (planning 1,000)
max_final_duration_years = 5; per_claim_alpha = 0.003125; power = 0.80 (z 2.734 + 0.842, inflation 1.5)
primary_series = all-session net strict-fill portfolio return, bp of E0 = Rs 5 L
bootstrap = stationary; expected_block 5; replicates 50,000; seed 20261026; robustness_blocks = fixed 10, 20
fee_model = per-fill, by fill date, Rs 20/order, broker-verified before the freeze
execution = gs/execution.py; passive results conditional on the fill model
minimum_counts_and_effect = >= 500 filled trades, >= 100 days, mean >= 1 bp/day
early_efficacy_looks = none (pilot futility only); safety = risk.py latches in the primary series
invalid_data = exposures kept unresolved with bounds, no silent deletion
verdicts = PASS / FAIL / INCONCLUSIVE / INFEASIBLE; amendment = new version, new sample
```

## Running exactly the frozen rules
- Each morning `bridge/gs_live.py` rebuilds the manifest from the files on disk and compares it with the frozen one in `nfce_bridge/data/gs.db`: code hashes, this protocol, fees, dependency lock and calendar. **Any difference and GS does not run that day** (fail-closed, shown in `/gs` and `/health`); the day then counts as missing data against coverage.
- **One exception, for data only:** the exchange calendar (`gs/calendar.py`) must be extended with NSE's 2027 holidays before 1 Jan 2027 (the list is published in December). An extension is accepted only when (a) `tests/test_gs_calendar.py::test_sessions_to_2026_never_change` passes unchanged (no existing session changed) and (b) it is recorded with `gs.registry.register_calendar_extension` plus a REGISTRY row. Nothing else may change.
- Every intent carries this file's SHA-256 (`protocol_hash`).

## Not allowed
- Changing a rule, threshold, cost, latency, size or statistic after the freeze, or looking at a stage before it is complete.
- Using touch fills, the M branch or a subgroup to claim a pass.
- Dropping sessions, or replacing a missing quote with a last price.
