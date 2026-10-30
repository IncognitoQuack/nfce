# Wider stops for stock 3m signals: result (22 Oct 2026, evening)

**Protocol:** `wide_stop_protocol.md`, SHA-256 `21912f803a8ecc660de5c0ac46aa422f347e1166b07e5d0d49e5907ed2c19283`, registered at 18:48 before the run.
**Code:** `nfce_engine/tools/wide_stop.py`. One engine run; the only change is the exits (`stock3m_research.trades(mults=...)`, with the default unchanged and engine tests 108 passing).
**Data:** 210 F&O stocks, Upstox 3m, current costs, one lot of about ₹7 L.

## Train 2022–24 (16,598 trades each): all three FAIL (Bonferroni, p < 0.0167 needed)
| Exits | Win % | Gross R | **Net R** | Day-block 95% | PF | Median cost share | ₹ (1 lot each) | Exits: target / stop / 15:15 |
|---|---|---|---|---|---|---|---|---|
| V0 (1R, reference) | 51.5 | +0.051 | −0.270 | −0.290..−0.249 | 0.66 | 29% | −93.9 L | 8,445 / 7,597 / 556 |
| K2 | 49.3 | +0.054 | **−0.107** | −0.127..−0.086 | 0.85 | 14% | −62.6 L | 6,487 / 5,583 / 4,528 |
| K3 | 47.6 | +0.053 | **−0.054** | −0.072..−0.035 | 0.91 | 10% | −41.2 L | 4,364 / 3,408 / 8,826 |
| K4 | 46.7 | +0.047 | **−0.034** | −0.049..−0.018 | 0.94 | 7% | −28.9 L | 2,854 / 1,989 / 11,755 |

Validation and the final stage are not run (no config passed train).

## What it shows
1. **Wider stops cut the loss a lot** (−0.27 → −0.03R per trade; rupees −69%), but never to a profit.
2. **The move runs out before costs are covered.**
   - At 4×, 71% of trades ride to the 15:15 close.
   - The gross move in the signal's favour is about +0.19 of the original R in price.
   - The futures round trip costs about 0.29 of the original R.
   - Wider still converges on "hold to the close", which cannot cover the cost either.
3. **So the entries carry a real but small directional drift; futures costs are bigger than it.** The only lever left on these entries is a **cheaper instrument**.
   - On 21–22 Oct live, the 1-ITM option legs of the same stock signals cost about a third as much per unit of exposure (₹2,941 vs ₹17,156 on the same 36 signals; the option has about half the delta).
   - There is no option history to backtest that; it can only be measured live.

## Action (before the 23 Oct open; no account has traded yet)
A sixth paper account, **WID4**, trades the K4 exits through options. It is an amendment to `strategy_accounts_protocol.md`, made before any data. WIDE keeps 2× for comparison.
