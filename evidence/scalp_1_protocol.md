# SCALP-1: order-book-imbalance scalping in liquid F&O cash stocks, passive entries (forward paper test)

**Registered** 27 Oct 2026, evening, before its first session (28 Oct). **Owner (27 Oct):** "tomorrow we will also do scalping … I expect profit in that as others also make it." This is also the "GS scalping with passive fills" test promised to the admin chat on 27 Oct.

## Honest prior, written before any data
- SEBI (FY23 study): about 71% of individual intraday cash traders lost money, and more among the most active.
- The published NSE evidence on 1–5 minute book-imbalance predictability (Gupta & Kumar 2025) is **2–5.5 bp gross**.
- Our cost at ₹5 L tickets is **4.53 bp a round trip in fees alone** (`gs/costs.round_trip_equity_bp`). Passive fills avoid the spread, but suffer adverse selection: a resting order is filled more often just before the price moves against it.
- **Expected verdict: FAIL.** The test exists to measure that, with real ticks, instead of assuming it.

## Data
`nfce_bridge/data/stream_YYYYMMDD.db` from the shadow streaming recorder (`ops/stream.py`, Upstox V3 `full` mode). It holds tick rows per instrument: receive time, last trade price, 5-level book, cumulative volume (`vtt`). Cash equities only (`NSE_EQ|…`). Simulated after the close by `nfce_engine/tools/scalp_sim.py`. No orders, no live interaction.

## Rules (one configuration; no tuning)
1. **Universe (fixed at 09:30 each day):**
   - candidates: the cash stocks whose **median quoted spread** (ask1 − bid1) / mid over the ticks 09:15:00–09:30:00 is ≤ **3.0 bp**;
   - of those, the **30 with the highest traded value** at 09:30 (`vtt` × last price).
2. **Entries:** 09:30:00–15:00:00. **All positions flat by 15:10:00** (before the 15:15 closing auction).
3. **Signal**, on each tick of a universe stock with no position or pending order in it:
   - L1 imbalance I1 = (bidQ1 − askQ1) / (bidQ1 + askQ1);
   - deep imbalance I25 = the same over levels 2–5, level k weighted by exp(−0.5(k−1)).
   - **Long** if I1 ≥ +0.60 and I25 ≥ +0.30. **Short** (intraday) if I1 ≤ −0.60 and I25 ≤ −0.30.
   - No new signal in a stock within 60 s of its last exit.
4. **Entry order:** passive limit at the touch of that tick (a long bids at bid1, a short offers at ask1).
   - Quantity: floor(₹5,00,000 / limit).
   - **Fill rule (conservative trade-through):** filled at the limit only if a LATER tick within 30 s trades strictly through it (last price < limit for a long, > limit for a short). Otherwise cancelled at 30 s, at no cost.
5. **Exits, after the fill**, checked on every later tick of that stock in this order:
   1. **Stop:** the opposite touch (bid1 for a long, ask1 for a short) is 8 bp or more against the entry. Exit marketable at that touch.
   2. **Target:** a resting limit 12 bp in favour. Filled when a later tick trades strictly through it.
   3. **Time stop:** 180 s after the entry fill. Exit marketable at the touch.
   4. **15:10:00:** marketable at the touch.
6. **Limits:** at most 2 open positions; at most 40 entry fills a day; **daily stop: once the day's realised net ≤ −₹10,000 (1% of a ₹10 L book), no new entries.**
7. **Fees:** every fill separately, through `gs/costs.equity_fill_fee` (flat ₹20 per order, STT 0.025% on sales, NSE, SEBI, stamp, GST).

## Measures
- **Daily unit:** net ₹ / ₹10 L, in bp per day. Also per-trade net bp and ₹.
- **Diagnostics, always reported:**
  - fill rate;
  - **adverse selection** (the mid-price move from the entry fill to +30 s, in the trade's direction, in bp);
  - hit rate;
  - gross bp vs fee bp;
  - exits by reason;
  - results by hour and by stock;
  - the tick cadence (seconds between ticks per stock).
- **Strict variant (reported):** the target fills only on a trade through by ≥ 1 more tick (`tick_size`, 0.05 by default).

## Stages and verdict
1. **Pilot: the first 10 sessions with stream data from 28 Oct.** Report everything daily. **Futility after 10:** if the one-sided 90% upper bound of the mean daily unit (block bootstrap, `nfce/stats.block_bootstrap_mean`) is < 0, SCALP-1 is **FAIL** and closed.
2. **Continue to 30 sessions.** It moves to a frozen 30-session **validation** only if all hold:
   - mean daily unit > 0 with its 95% lower bound > 0;
   - ≥ 300 trades;
   - the strict variant's total net > 0.
3. **Validation (30 more sessions, rules frozen):** the same conditions. Only then may a live-paper account be proposed to the owner.

## Not allowed
Changing any threshold (imbalance, 12/8 bp, 30/180 s, the universe rule, ticket size) after seeing any result. Reporting a better-looking variant as the result. Dropping sessions. A failed SCALP-1 may be followed only by a NEW registration (SCALP-2), never by re-tuning this one.
