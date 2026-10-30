# 3-session paper simulation: result (15, 16, 19 Oct 2026)

Protocol: `sim3d_protocol.md` (SHA-256 `f3d22a3cd8162fcc…`, fixed before any result). Tool: `nfce_engine/tools/sim3d.py`.
Full per-trade output: `sim3d_result.json` in the session scratchpad (SHA-256 `839746dfefdd6585…`); regenerate with the tool.

**Universe:** the 50 Nifty stocks, plus NIFTY and BANKNIFTY spot with heavyweight proxy volume.
**Timeframes:** 5m and 15m. **Data:** Yahoo, with 60 sessions of warm-up.
**Costs:** the dated futures fee schedule, plus 4 ticks friction per side.

| Variant | Trades | Win % | Gross R | Net R | 15–16 Oct (in-sample) | 19 Oct (out-of-sample) | Paper ₹ |
|---|---|---|---|---|---|---|---|
| V0 base | 55 | 35 | −0.108 | **−0.404** | −0.551 (35) | −0.146 (20) | −50,765 |
| V1 single exit 2R | 55 | 29 | −0.078 | −0.372 | −0.482 (35) | −0.182 (20) | −9,416 |
| V2 lean volume+HTF | 53 | 34 | −0.005 | −0.325 | **−0.344** (39) | −0.270 (14) | −63,844 |
| V3 volume hard filter | 3 | 67 | +0.430 | +0.146 | +0.146 (3) | — (0) | −744 |
| V4 no entry after 13:30 | 31 | 35 | −0.103 | −0.345 | −0.532 (18) | −0.086 (13) | −24,213 |

**Base, by day:**

| Day | Trades | Net R | Win % |
|---|---|---|---|
| 15 Oct | 16 | −0.74 | 25 |
| 16 Oct | 19 | −0.39 | 32 |
| 19 Oct | 20 | −0.15 | 45 |

**Base, other splits:**
- **Exits:** 27 square-offs, 20 stops, 6 breakeven/trail, 2 T3.
- **Instruments:** only 2 of the 55 trades were index trades (NIFTY 5m stop −1.41R, BANKNIFTY 5m +1.10R).
- **Best / worst:** HINDALCO 5m long +1.43R; TMPV 5m long −1.78R.

**Selection (per protocol):** V2 was best in-sample but did worse than V0 out-of-sample, so it was **not adopted**. V3 was excluded (fewer than 10 in-sample trades).

**Conclusions:**
- **No change is made to the live system.**
- **Day-block intervals are crude:** with only 3 day-blocks they are not reliable. The defensible statement is "negative on every day, every variant with a usable sample".
- **Rupee totals mix position sizes,** so R is the comparable unit.

Posted to Telegram on 19 Oct 2026, ~20:00 IST.
