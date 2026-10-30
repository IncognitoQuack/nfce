# Overnight defined-risk NIFTY option selling: forward paper test (registered 26 Oct 2026, before the first entry at 15:20)

**Why:** the research note (`research_how_systems_are_built.md`, test 2) found peer-reviewed India evidence (NIFTY options 2017–20) that short option positions are paid for **overnight** risk, while intraday short returns are mostly zero or negative. It is the only premium in the project with that kind of evidence. Short options carry crash risk, so **only defined-risk structures** are tested.

**Type:** a forward paper test. No orders are placed. Entries and exits are read after the fact from the recorded option chains (`nfce_bridge/data/study_chain_YYYYMMDD.db`, `ops/collect_chain.py`, one snapshot a minute). Every rule below is mechanical, so there is no discretion left once this file is hashed.
**Scorer:** `nfce_engine/tools/overnight_options.py`; tests `nfce_engine/tests/test_overnight_options.py`.

## Each session d (a trading day with a recorded chain)
1. **Entry snapshot:** the first NIFTY snapshot with time ≥ **15:20:00** on day d.
2. **Expiry:** the nearest NIFTY expiry that is **after the next trading session** (so the position never expires overnight and the exit is not on expiry morning). On 26 Oct, that is 3 Nov.
3. **Spot S** = the chain's spot. **ATM strike K** = the strike nearest S (strike step 50).
4. **ATM IV σ** = the mean of the CE and PE `iv` at K, in %. **Overnight 1-SD move:** `SD = S × σ/100 × √(1/252)`.
5. **Two structures, each one lot of 65:**
   - **IF (primary): an ATM iron fly.** Sell the K call and the K put; buy the call at K + W and the put at K − W, where **W = 2 × SD rounded UP to a multiple of 50**.
   - **IC (secondary): an iron condor.** Sell the call at K + a and the put at K − a, where **a = SD rounded to the nearest 50** (at least 50). Buy the call at K + a + W and the put at K − a − W, with **the same W**.
6. **Fills:** sold legs at the recorded **bid**, bought legs at the recorded **ask**, in the entry snapshot. If any leg has no positive bid and ask, the structure is **not entered** (logged as "no quote").
7. **Filters (a session is skipped, and logged with the reason, if either holds):**
   - **F1, volatility rising:** the ATM IV of the chosen expiry at 15:20 is ≥ **1.05 ×** its value in the first snapshot at or after **11:00** the same day (at the strike that was ATM then).
   - **F2, range model expects a large move:** NIFTY's last `M1` range forecast of the day in `nfce.db.range_forecasts` (latest bar_close ≤ 15:20; `exp(q50)`) is above the **80th percentile** of the same last-of-day forecasts of all earlier sessions since 21 Oct 2026. F2 applies only once there are ≥ 5 earlier sessions; before that it is logged as "not active".
   - The **unfiltered** version (every session entered) is also scored, for information only.

## Exit (next trading session d+1)
- **Exit snapshot:** the first snapshot with time ≥ **09:16:00**, to avoid the opening auction's quotes.
- **Fills:** buy back sold legs at the **ask**, sell bought legs at the **bid**.
- **A leg without a positive bid and ask:** take the next snapshot, up to 09:30. If there is still none, that leg is marked at its last traded price, plus (or minus) **1.5×** its entry spread, against us, and the session is flagged.
- **If d+1 has no recorded chain:** the session is **unresolved**. It is reported, and it does not count toward the 40.

## Costs
- **Fees:** `costs.option_fees` per leg at the current schedule: option STT 0.15% of the sell premium (from 1 Apr 2026), NSE 0.03553%, SEBI, stamp, ₹20 per order (8 orders), and GST.
- **Spreads:** paid in full through the bid/ask fills.

## Units
- **Net ₹ per session** (one lot), after fees.
- **R** = the structure's maximum loss = (W − net credit) × 65, after entry fees. **Net R** = net ₹ / R.

## Judgement
- **When:** after **40 entered sessions** of the filtered IF (expected ≈ 45–60 trading days), and once only. IC is judged at the same moment.
- **Pass (each structure; family of 2, Bonferroni, so p < 0.025):** all three of
  1. mean net ₹ per entered session > 0;
  2. a one-sided t-test on the per-session net ₹ gives p < 0.025;
  3. the mean is still > 0 when **every** entry and exit spread is widened 1.5×.
- **Also reported:**
  - win rate and the worst session;
  - max drawdown, in ₹ and in R;
  - skipped sessions by reason;
  - unfiltered vs filtered.
- **Stress check (reported, not a pass condition):** on `hist5m_index` NIFTY 2022–26:
  - the overnight gap (15:20 close → next 09:15 open) in units of the overnight SD implied by INDIA VIX (the prior day's close, `hist3m_fo`);
  - the share of nights beyond 1 SD (IC's short strikes breached) and beyond 2 SD (IF at its maximum loss);
  - the 10 worst nights;
  - how many average credits one maximum loss erases.

## What a pass would and would not mean
- **A pass** means the overnight premium survived real recorded spreads and fees for 40 sessions. The next step would be a separate, registered paper account with sizing rules, **never real money directly**.
- **40 sessions cannot prove the tail risk.** That is why the stress check and the defined-risk wings are required.
- **A fail** closes the overnight-premium lead for NIFTY weeklies at these strikes.

## Not allowed
- Changing a strike rule, the timing, a filter or the costs after seeing any result.
- Dropping sessions.
- Looking at the IC numbers to pick between IF and IC: both are reported as registered.
