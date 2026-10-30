# Phase 6: simpler ideas on 3 years of real data, and paper-trading validation (18 Oct 2026)

> **Corrected in v2 (PHASE7_V2_EVIDENCE.md §C and §E).**
> - **Costs:** the costs below are the 2026 schedule applied to 2023–2026 trades, a stress test and not historical P&L.
> - **Significance:** at historical costs, 7 of 8 variants are not significantly different from zero, and one (NIFTY H2 momentum) is significantly negative. "Not bad luck" was overstated.
> - **Period:** "3 years" means 727 sessions (Yahoo's ~730-calendar-day maximum).
> - **Tests:** the test counts below are v1 counts.

## A. Two simple, pre-registered hypotheses
- **Data:** Yahoo Finance 60-minute bars, NIFTY 50 and NIFTY BANK spot, 2 Nov 2023 – 16 Oct 2026 (727 sessions each).
- **Costs:** the same model as every other test: 0.03% of notional per side + 4 ticks per side. That's ≈15 Nifty points or ≈33 Bank Nifty points per round trip, per lot.
- **Splits:** out-of-sample = last 30% of sessions (from 26 Nov 2025).
- **Code:** `nfce_engine/nfce/simple.py` (rules) and `nfce_engine/tools/simple_ideas.py` (runner).
- The rules were fixed before any result was seen. Every variant is reported.

| Hypothesis | Index | Trades | Gross pts/trade | Net pts/trade | t | In-sample net | Out-of-sample net | Net ₹/lot (3 yrs) |
|---|---|---|---|---|---|---|---|---|
| H1 ORB, stop = other side | NIFTY | 544 | +6.6 | **−8.5** | −2.1 | −7.8 | −10.2 | −3.0 L |
| H1 ORB, stop = midpoint | NIFTY | 544 | +8.3 | **−6.8** | −1.8 | −7.8 | −4.6 | −2.4 L |
| H2 momentum, all days | NIFTY | 724 | −0.6 | **−15.7** | −7.1 | −16.7 | −13.5 | −7.4 L |
| H2 momentum, big first hour | NIFTY | 285 | +2.2 | **−12.9** | −3.5 | −17.3 | +0.7 | −2.4 L |
| H1 ORB, stop = other side | BANKNIFTY | 533 | −1.3 | **−34.8** | −3.2 | −33.7 | −37.1 | −5.6 L |
| H1 ORB, stop = midpoint | BANKNIFTY | 533 | +2.5 | **−31.0** | −3.1 | −35.8 | −20.7 | −5.0 L |
| H2 momentum, all days | BANKNIFTY | 724 | +3.5 | **−30.0** | −5.0 | −37.4 | −12.9 | −6.5 L |
| H2 momentum, big first hour | BANKNIFTY | 281 | +1.9 | **−31.3** | −3.2 | −41.7 | −0.1 | −2.6 L |

**Result: all 8 variants lose money after costs over 3 years**, with 281–724 trades each, so this is not bad luck.
- **Gross edges are close to zero.** The best is +8 Nifty points per trade. The futures round trip costs ~15.
- **The "big first hour" variants are about break-even out-of-sample, after being clearly negative in-sample.** That pattern is what random variation looks like. It is not a reason to trade them.

**What this means for the whole project:**
- For index futures held intraday, costs of ~0.06% of notional per round trip are larger than the gross edge of every idea tested so far: NFCE, ORB and momentum, on Nifty and Bank Nifty, at 5m, 15m and 60m.
- Any intraday futures system on these indices needs a gross edge comfortably above ~15 Nifty / ~33 Bank Nifty points per trade before it can make money.

## B. Paper trading: built and validated (live run waits for your Upstox keys)
- **What it does:** `nfce_bridge/bridge/paper.py` follows every signal forward on live prices, using the exact rules and costs of the backtests:
  - 40/30/30 booking;
  - breakeven after T1, trail to T1 after T2;
  - square-off at 15:15;
  - stops as resting SL-M orders.
- **Vetoed signals are kept as shadow trades,** so the option-chain veto rule is measured, not assumed.
- **Telegram:** a message on every close, a daily summary after 15:20, and the `/paper` command.
- **Validation:** I replayed 60 days of real Nifty 5m data through the paper ledger as if it were a live feed (`nfce_engine/tools/paper_replay.py`). **It reproduced the engine's trades exactly: 15/15 identical.**
- **Tests:** 37 bridge tests and 24 engine tests, all passing.
- **Not done:** live paper trading itself. It needs a market session and your Upstox keys; nothing about it can be simulated honestly beyond the replay above.
