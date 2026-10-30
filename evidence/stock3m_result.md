# 3-minute NFCE on F&O stocks, and EARLY mode: results (21 Oct 2026, evening)

**Protocols:**
- `stock3m_protocol.md`, SHA-256 `1adecd083510bf861df6aef7333d6e4fb2f9deb8b80706722f01a49ff52cfed3`;
- `early3m_protocol.md`, SHA-256 `a652333949eda792c221287364baed050e4b64315461fe2e94a5e5fa8b5ec5d3`.

Both were hashed before any result.

**Data:** Upstox 3m candles, 50 NIFTY-50 stocks + India VIX, 2022-01 to 2026-10-19, pulled on 21 Oct.
**Code:** `nfce_engine/tools/stock3m_research.py`.

## Train stage, 2022–2024 (current costs, one lot, all out at T1)
| Variant | Trades | Win % | Gross R | **Net R** | Day-block 95% | PF | Paper ₹ |
|---|---|---|---|---|---|---|---|
| V0, every signal (as live on 21 Oct) | 4,460 | 50.7 | +0.041 | **−0.338** | −0.369..−0.306 | 0.57 | −27.3 L |
| V1, cost share ≤ 20% | 468 | 52.1 | +0.057 | **−0.099** | −0.203..−0.002 | 0.84 | −2.0 L |
| V2, cost share ≤ 10% | 42 | 52.4 | +0.026 | −0.052 | −0.280..+0.234 | 0.85 | −0.3 L |

- **Cost share of risk:** median 35% (10th percentile 20%, 90th 59%).
- **No variant survives training**, so validation and the final stage are not run.
- **What it means:**
  - The 3m stop is so close that costs take about a third of the risk, against an edge before costs of about +0.04R.
  - Filtering out the expensive signals leaves too little edge and too few trades.
  - This confirms the live day (22 of 37 won, yet −₹13,884: costs were 5.2× the gross).

## EARLY mode, first 15 minutes (`skip_open = 0`, entries on bars closing ≤ 09:30)
- **E0 and E1: zero trades in 4.5 years.**
- **Diagnosis** (engine trace, TCS 2024): in the first 15 minutes the engine's own rules block every bar: "no breakout" 227 bars, score/risk/room 128 bars, chop/ATR not yet formed.
- **Why:** the opening range and the room-to-level checks cannot be satisfied while the opening range is still forming.
- **So:** the EARLY provision added on 21 Oct (09:57 request) **could never fire.** It fails its protocol.

## Applied (as each protocol's "Use" section says)
1. **Stock 3m signals:**
   - not traded as futures by the paper account;
   - they stay as information, with the tested result shown in every message;
   - their option legs are traded by the account only as a small live experiment, at **0.25× normal risk** (`STOCK_SIGNAL_RISK = 0.25`).
2. **EARLY mode:**
   - the account risk is 0;
   - replaced by an **opening watchlist at 09:21 and 09:30** (early gainers, losers and unusual volume), information only.
   - Opening-momentum trading needs a rule designed for the open (for example an opening-range breakout on volume), which would be a new pre-registered study. The index ORB research (84 configurations) found no edge at current costs.
