# GS-SIP-1 development test on history: pre-declared rules (26 Oct 2026, evening, before any historical scoring)

**Why:** the owner (via the main session, ~16:10) asked to "count GS" from 27 Oct with "real figures", to improve it today only from information already in hand, and to run a random test on all available data. This file fixes how that is done **before** any GS-SIP-1 number on history is computed. Hashed into REGISTRY first.
**What it is not:** a pass/fail test of the edge. 2022–26 bars are development data, already partly seen through study engine v2 (its H2 is the same idea with different timing). The only test that can establish anything is the forward GS-SIP-1 pilot/validation/final from 27 Oct. **No profit claim follows from this file, whatever it shows.**

## 1. Data
- 3-minute candles `~/Downloads/nfce_data/hist3m_fo/` (213 F&O stocks, 2022-01-03 → 2026-10-19; today's survivors: survivorship bias, stated); daily candles `nfce_data/daily/` (to 23 Oct) for ATR14 and the previous close; INDIAVIX daily for the regime.
- Exchange calendar `nfce_engine/gs/calendar.py` (sessions, events).
- **Spreads:** per stock and time-of-day bucket, the median half-spread (bp of mid) from the recorded quote files `nfce_bridge/data/study_quotes_2026102{2,3,6}.db`; buckets 09:15–09:30, 09:30–10:00, 10:00–11:30, 11:30–14:00, 14:00–15:30; a stock or bucket without data takes the all-stock median of that bucket. Spreads of three days in Oct 2026 are applied to all years (a stated approximation).
- **Fees:** `gs/costs.py` per fill at the current schedule (₹20/order, STT 0.025% on sales, NSE, SEBI, stamp, GST): "current-cost" history.

## 2. The as-designed rule (GS-SIP-1, `gs_sip_1_protocol.md`), translated to bars
- **Selection at 09:21:** both bars 09:15 and 09:18 present; RVOL = (their volume) / mean of the same window on each of the 14 previous calendar sessions (all present and > 0); RVOL ≥ 1; ATR14 (Wilder, 100 sessions to the previous session) / previous close ≥ 1%; top 20 by RVOL (ties by symbol); direction = sign(09:18 close − 09:15 open), 0 = skip; boundary = the opening range's high (long) / low (short).
- **Trigger:** the first bar starting ≥ 09:30 and closing ≤ 11:30 whose close is beyond the boundary. Decision at that bar's close.
- **Bid/ask proxy at the decision:** close ∓ the half-spread.
- **Branch M (marketable):** entry = the NEXT bar's open + the half-spread (long; − for a short).
- **Branch P (passive):** limit = min(boundary, bid) for a long, max(boundary, ask) for a short, rounded against aggressiveness to ₹0.05; the order lives for the next bar only (180 s ≈ one 3-minute bar; never past 11:33).
  - **P strict:** filled at the limit if the next bar trades through it by ≥ 1 tick (low ≤ limit − 0.05 for a long; high ≥ limit + 0.05 for a short).
  - **P touch:** low ≤ limit (illustration only).
  - **P adverse:** from P strict, the best 25% of filled trades set to zero and 2 bp of notional charged on the rest.
  - **Bars cannot prove passive fills** (no queue, no size at the price); P figures are scenarios, not evidence.
- **Exit:** stop at the fill ∓ 0.5 × ATR14, checked from the fill bar on (a fill bar that also reaches the stop counts as stopped: conservative); the exit price is the stop, or the bar's open if it gapped past the stop, minus the half-spread; otherwise the 15:15 bar's open minus the half-spread. No target.
- **Size and limits:** ticket ≤ ₹1 L; risk 0.25% of ₹5 L × the VIX regime (1 / 0.5 / 0.25 at VIX ≤ 20 / ≤ 25 / > 25 or up > 20% in 5 sessions) with stress loss per share = 0.75 ATR + half-spread + fees per share; at most 4 positions open or pending at once (first come, by decision time); DG latch (realized day peak ≥ ₹2,500 and back to half: no new entries); RBI-policy days: no entries 09:30–10:30; Budget days: none. The drawdown pause is **not** simulated (in a backtest it would stop the series at the first 5% drawdown); this is stated in the results.
- **Primary series:** daily net ₹ / ₹5 L in bp, every session (zero when nothing fills).

## 3. Reporting
- Per year 2022–26 and for 2022–24 / 2025–26: sessions, opportunities (triggered selections), fills, gross and net bp per filled trade (on notional), net bp per day of ₹5 L, and a 95% day-block CI of the daily mean (stationary bootstrap, block 5, 50,000 replicates, seed 20261026, `gs/evaluate.py`), for M, P strict, P touch, P adverse.
- **Random test:** a seeded random sample (seed 20261026) of 250 sessions from 2022–24, and all sessions of 2025–26, reported alongside the full run (the same simulation; the sample is a subset of days).

## 4. Improvements: at most three, each with its reason, decided before scoring
Single changes only (no combinations), each against the as-designed rule (A0):
- **C1, stop 1.0 × ATR14 instead of 0.5 ×.** Reason: intraday noise is about 0.5 ATR, so a tight stop exits continuation trades early; in the project's 16,598-trade stock study, wider stops lost less (−0.27R at 1× → −0.11R at 2× → −0.03R at 4×). Cost: half the quantity at the same risk, so fixed brokerage weighs more per bp.
- **C2, RVOL ≥ 2 instead of ≥ 1** (still the top 20). Reason: the hypothesis is institutional flow; a doubled opening volume is a stronger sign that the stock is in play than "above average", and the US stocks-in-play result is concentrated in the highest relative volume. Cost: fewer trades.
- **C3, trigger window to 10:30 instead of 11:30.** Reason: the continuation from opening information is expected to be strongest early; late first breakouts are more likely to be ordinary range noise, and they have less time to run before 15:15.

**Selection rule:**
1. On **2022–24 only**, a candidate qualifies if its net bp/day beats A0 under **both** P strict and M.
2. Of the qualifiers, the one with the highest 2022–24 P-strict net bp/day is the single winner (ties: C1 < C2 < C3 order).
3. The winner is checked **once** on 2025–26 (development-exposed: a check, not a final). It is **adopted** only if it also beats A0 on 2025–26 under both P strict and M. Otherwise A0 is kept.
4. No other variant is scored. No threshold is tuned. The 2025–26 numbers of non-winning candidates are not computed before the decision; after it, they may be reported for transparency only.

## 5. After this file
The adopted rule (A0 or the winner) is written into `gs_sip_1_protocol.md`, which is frozen (status REGISTERED) with its manifest tonight; the forward pilot starts with the first session, 27 Oct 2026. These historical numbers never count toward the forward test.
