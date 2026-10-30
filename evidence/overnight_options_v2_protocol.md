# Overnight NIFTY iron fly, v2 (= GS-OVN-1): forward paper test (registered 26 Oct 2026, before the 15:20 entry)

**What this is:** version 2 of `overnight_options_protocol.md` (v1, SHA `30f95dab…0a64`). It is the GS-OVN-1 rule of `GS_ENGINE_FINAL_BLUEPRINT.md` section 5 (approved by the owner on 26 Oct 2026: a ₹10 L virtual book). It fixes five faults that review "A" (`~/Downloads/GS_engine_blueprint.md` section 2) found in v1, and that were confirmed in the code on 26 Oct:
1. v1 took the "next session" from the next recorded file, so a missing day turned an overnight trade into a multi-day one. **v2 takes it from the exchange calendar** (`nfce_engine/gs/calendar.py`).
2. v1 marked a leg without a quote at its last traded price and still counted the session as `ok`. **v2 never substitutes a last price**: the leg stays open and the structure is *unresolved*.
3. v1 counted half the round-trip fees as "entry fees". **v2 charges entry fees from the four entry fills only, and reserves exit fees separately, before entry**, from a stress grid, not from the realized exit.
4. v1 set the wings from the 15:20 IV × √(1/252), an uncalibrated overnight SD. **v2 sets them causally: 1 × the previous session's ATR14, rounded up to the strike step.**
5. v1 had no capital or risk budget. **v2 runs in a ₹10 L virtual book with a 0.5% (₹5,000) budget per structure, including fees.**

**v1 status:** superseded before its first entry. Its code path (`overnight_options.py score`) is kept unchanged and can still be run for information; its judgement (40 sessions, t-test) is **withdrawn** and will not be reported as a verdict.

**Type:** forward paper test. No orders. Entries and exits are read after the fact from the recorded option chains (`nfce_bridge/data/study_chain_YYYYMMDD.db`), one snapshot a minute.
**Scorer:** `nfce_engine/tools/overnight_options.py score2` (`score_v2`); tests `nfce_engine/tests/test_overnight_v2.py`. Fees: `nfce_engine/gs/costs.py` (wraps the frozen `nfce/costs.py`). Lot size: `nfce_engine/gs/instruments.py`.
**First entry:** 26 Oct 2026 at 15:20 (if the chain is recorded then). First exit: 27 Oct 2026 from 09:20.

## Each exchange session d (from 26 Oct 2026)
Every regular NSE session in the calendar is a row, whether or not anything was recorded or entered.

1. **Data:** the chain file for d. If it is missing, the row is *missing data* (counts against coverage, P&L 0).
2. **Causal inputs** (all from completed sessions up to the previous session d−1, from `nfce_data/daily/NIFTY_1d.pkl` and `INDIAVIX_1d.pkl`):
   - **ATR14:** Wilder's average true range over the 100 sessions ending at d−1, seeded with the mean of the first 14 true ranges of that window.
   - **VIX:** the previous close V and its change over 5 sessions (V(d−1)/V(d−6) − 1).
   - If d−1's daily bar is not loaded yet, the row is *pending* until it is; nothing else changes.
3. **Skip** (logged with the reason, P&L 0):
   - V > 25, or the 5-session VIX change > +20%;
   - a scheduled event (RBI policy announcement, Union Budget, national-election counting; list in `gs/calendar.py EVENTS`) on a date after d and up to the next session;
   - an earlier structure still has open legs (*blocked*).
4. **Regime size:** V in (20, 25] halves the budget to ₹2,500.
5. **Entry snapshot:** the first NIFTY snapshot with time in **[15:20:00, 15:21:00)**. None → *no entry snapshot* (a data failure: counts against coverage). All four legs come from that one chain response.
6. **Expiry:** the nearest **listed** expiry strictly after the next exchange session (so the exit is never on expiry day and no expiry-day contract is used).
7. **Strikes:** spot S = the chain's spot. **K** = the listed strike nearest S (a tie goes to the lower strike). Wing target **w = ceil(ATR14 / step) × step** (step = the smallest listed strike gap, 50 for NIFTY). Call wing **Kc** = the lowest listed strike ≥ K + w; put wing **Kp** = the highest listed strike ≤ K − w. Widths Wc = Kc − K, Wp = K − Kp.
8. **Structure (an iron fly):** buy the Kc call and the Kp put (**wings first**), then sell the K call and the K put.
9. **Quotes:** every leg needs bid > 0, ask > 0 and ask ≥ bid, or the structure is not entered.
10. **Fills:** bought legs at the ask, sold legs at the bid. Net credit C (points) = bid(K call) + bid(K put) − ask(Kc call) − ask(Kp put). Enter only if **0 < C < min(Wc, Wp)**.
11. **Fees:** each fill separately (`gs/costs.option_fill_fee`): STT 0.15% on option sales, NSE 0.03553% each side, SEBI ₹10/crore, stamp 0.003% on buys, ₹20 brokerage per order, GST 18% on brokerage + exchange + SEBI. Entry fees = the four entry fills.
12. **Exit-fee reserve:** the largest exit fees over a stress grid at the scheduled exit (next session 09:20): spot −10%, −7%, −5%, −3%, 0, +3%, +5%, +7%, +10%; each leg's IV −10, 0, +10, +20, +40 points; spreads ×1, ×2, ×5; Black-Scholes marks with r = 0 and time to the expiry's 15:30.
13. **Size:** the largest whole number of lots (lot from `gs/instruments.py`; 65 now) for which
    **reserve = (max(Wc, Wp) − C) × qty + entry fees + exit-fee reserve ≤ budget** (₹5,000, or ₹2,500 at half size),
    each leg's visible size (ask size for buys, bid size for sells) covers the quantity, and 1.25 × max(W) × qty ≤ ₹10 L (collateral, margin not modelled). Zero lots → *not entered* (logged with the one-lot reserve).

## Exit (the next exchange session from the calendar)
- **Order:** both shorts are bought back first, each at the ask of the first snapshot from **09:20:00** where it has a valid quote. Then both wings are sold, each at the bid of the first valid snapshot at or after the later short exit.
- **Missing quotes:** a leg with no valid quote by 15:15 stays open and is tried on the following sessions (up to 4 more). Its structure is **unresolved**: it has no certified P&L, it blocks new entries, and it is carried with two bounds: worst = −reserve, best = C × qty − entry fees − exit-fee reserve. No last-traded-price mark is ever used.
- **A structure closed after its scheduled exit session** is flagged *late*; no entry is made until its legs are closed.
- **No target, no stop, no roll, no added exposure.**

## Units
- **Daily unit u(d) = net ₹ of the structure entered on d / ₹5,000** (the fixed full budget, even at half size). Days with no entry: u = 0. Missing-data days: u = 0 and they count against coverage. Pending days are not scored until their input is loaded.
- **Widened:** the same structure, lots and exit times re-priced with every entry and exit half-spread × 1.5 (`units_widened`).

## Judgement (blueprint section 9; GS common contract)
Statistics: **stationary block bootstrap** (Politis–Romano) on the daily series u, expected block length 5 sessions, 50,000 replicates, seed 20261026; implemented in `nfce_engine/gs/evaluate.py`, whose file hash is added to REGISTRY before the first stage decision. Unresolved structures enter the series at their **worst** bound, except in the futility check, where they enter at their **best** bound (so a missing quote can neither manufacture a pass nor force a kill).

1. **Stage 1, pilot: the first 60 exchange sessions from 26 Oct 2026.** Measure data quality, fill feasibility, fees and the SD of u. **Futility stop:** if the one-sided 90% upper bootstrap bound of mean u is **< 0**, OVN v2 is closed (FAIL). Otherwise compute the final length (step 3) from the pilot SD and continue. Nothing about the rules may change.
2. **Stage 2, validation: the next 60 sessions, rules frozen.** Continue only if all hold: total net ₹ > 0; total widened net ₹ > 0; coverage (sessions not *missing data* / *no entry snapshot*) ≥ 95%; ≥ 20 entered structures. Otherwise FAIL (or INFEASIBLE if fewer than 20 structures could be entered because of the budget or visible size).
3. **Final length N:** `N = ceil(1.5 × ((2.734 + 0.842) × σ / 0.05)²)` sessions, σ = the pilot SD of u (planning value 700). If N sessions cannot be completed within 5 calendar years (≈ 1,240 sessions), the verdict is **INFEASIBLE**, stated honestly, and the final is not run.
4. **Stage 3, final: the next N sessions, one look only, at α = 0.003125** (one of the 16 GS claim slots). **PASS** requires all of:
   - the null-centred one-sided bootstrap p < 0.003125 at block 5, **and** at fixed blocks 10 and 20 (both extra hurdles);
   - the 99.6875% one-sided lower bound of mean u > 0;
   - mean u ≥ 0.05 (₹250 a session);
   - total net ₹ > 0 and total widened net ₹ > 0;
   - ≥ 250 complete structures, coverage ≥ 95%;
   - no unresolved structure that could flip the verdict (if one could, the verdict is INCONCLUSIVE).
   Otherwise **FAIL** (or **INCONCLUSIVE** if the counts are short).
- **Verdicts:** PASS / FAIL / INCONCLUSIVE / INFEASIBLE. No extension after seeing results. Any rule change is a v3 with a new sample.

## Also reported (not pass conditions)
- Skips and non-entries by reason; fills, credits, reserves, lots; late and unresolved structures; exit delays.
- **Stress diagnostic** (`overnight_options.py stress2`): historical NIFTY overnight gaps (15:20 close → next calendar session's open) in units of the causal previous-day ATR14, i.e. of the wing; nights with a missing next-session bar are listed, not silently paired.
- 40 or 60 quiet sessions say little about the tail: at a 1% chance a night of a maximum loss, 60 nights pass without one 55% of the time.

## Not allowed
- Changing a strike rule, the timing, a gate, the budget, the fees or the statistics after seeing any result.
- Dropping or re-labelling sessions.
- Replacing a missing quote by a last traded price.
