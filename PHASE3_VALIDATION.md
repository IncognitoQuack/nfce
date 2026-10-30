# NFCE — Phase 3: validation report (17 Oct 2026)

## Verdict
**No edge survives costs, on any instrument or timeframe tested.** Do not trade this system with real money in its current form.

| | Gross (before costs) | Net (after costs) |
|---|---|---|
| Pooled, 98 trades (NIFTY & BANKNIFTY, 5m & 15m) | **+0.10R** per trade (95% CI −0.06 to +0.29) | **−0.19R** per trade (95% CI −0.37 to 0.00) |

- Costs are about 0.06% round trip plus slippage, which is **≈0.30R per trade**. That is three times the gross edge.
- The only positive cell, BANKNIFTY 15m (+0.04R net, 31 trades), is statistically zero.
- Its out-of-sample part is 6 trades.

## Data and method
- **Source:** `nfce_strategy.pine` on TradingView, using all history available on your plan.
  - 5m: 13 Jul – 16 Oct 2026.
  - 15m: 1 Dec 2025 – 16 Oct 2026.
- **Ledger:** the same state machine as the indicator. It agrees with TradingView's broker emulator within ~1–2%.
- **Costs:** 0.03% of notional per side + 4 ticks per side. R is the entry-to-SL distance.
- **Out-of-sample:** first 70% of each chart's period vs last 30%.
  - 5m cut: 17 Sep 2026.
  - 15m cut: 12 Jul 2026.
- **Sample size is the main limitation.**
  - 98 trades pooled, and only 26 of them out-of-sample.
  - Differences of less than ~0.2R between variants are within noise.
  - The report's own bar is 200+ trades per instrument and timeframe; no cell here gets close.

## 1. Splits (base settings, 4 runs pooled, net R per trade)
| Split | Result |
|---|---|
| **By month** | Positive in Jan (+0.22, n6), Mar (+0.34, n9), May (+0.11, n7), Oct (+0.08, n8). Negative in Dec, Feb, Apr, Jun, Jul, Aug (−0.89, n13) and Sep. No stable regime. |
| **By entry hour (IST)** | 09h −0.37 (n6) · 10h −0.23 (n24) · 11h −0.27 (n24) · **12h +0.29 (n16)** · 13h −0.37 (n8) · 14h −0.37 (n17) · 15h 0.00 (n3). The 12h bucket covers entries 12:00–12:30, just before the lunch filter. It is the only positive hour, with too few trades to act on. |
| **Expiry vs other days** | Expiry **+0.57R (n6)**, other days −0.24R (n92). Six trades is not evidence. The +10 score requirement and the 13:30 cutoff already keep expiry trades rare. |
| **Grade** | A+ (≥80) −0.14R (n54) vs A −0.25R (n44). A+ is marginally less bad but still negative. In NIFTY 15m, A+ was +0.09R (n21) and A was −0.41R (n17). |

Per run:

| Run | A | A+ | In-sample | Out-of-sample |
|---|---|---|---|---|
| NIFTY 5m | −0.55 | −0.43 | −0.64 (n15) | +0.13 (n4) |
| NIFTY 15m | −0.41 | +0.09 | −0.14 (n27) | −0.11 (n11) |
| BANKNIFTY 15m | +0.15 | −0.06 | +0.04 (n25) | +0.05 (n6) |
| BANKNIFTY 5m | −0.53 | −0.66 | −0.71 (n5) | −0.50 (n5) |

**Exit mix: 44% of trades end at the 15:15 square-off.**
- Base exits: 34 SL, 16 BE/trail stop, **only 5 reach T3**, 43 square-offs.
- The 3R target is rarely reached within a day, so most of the planned upside never happens.

## 2. Out-of-sample (first 70% vs last 30%)
- Base: in-sample −0.22R (n72), out-of-sample −0.11R (n26).
- Neither half is positive. The out-of-sample half is less negative, but at n = 26 that is noise.

## 3. Ablation (one factor weight set to 0, everything else unchanged)
| Factor removed | Pooled n | Pooled net R | OOS total R (base −2.9) | Reading |
|---|---|---|---|---|
| none (base) | 98 | −0.19 | −2.9 | |
| Volume surge | 103 | −0.24 | −2.9 | **Helps** (removing it is worse) |
| Higher timeframe | 107 | −0.23 | −4.2 | **Helps** (removing it is worse, in and out of sample) |
| Directional consistency | 98 | −0.19 | −1.6 | No measurable value |
| Trend stack (EMA/VWAP) | 94 | −0.19 | −1.6 | No measurable value |
| ADX/DMI | 95 | −0.20 | −1.6 | No measurable value |
| CVD (approx.) | 98 | −0.16 | −1.6 | Removing it slightly *improves* results |
| Futures OI | 93 | −0.19 | −2.9 | No measurable value |
| Heavyweights | 100 | −0.19 | −2.9 | No measurable value |
| India VIX | 97 | −0.18 | −1.6 | No measurable value |
| *Volume as hard filter (on)* | 16 | −0.15 | +1.0 (n2) | Too few trades to judge |

**Recommendation, by the report's own rule** ("if removing a factor does not lower out-of-sample expectancy, drop it"):
- Keep **Volume surge** and **Higher timeframe**.
- Seven factors show no value here: Directional, Trend stack, ADX, CVD, Futures OI, Heavyweights, VIX.
- Directional, Trend stack, ADX and HTF are largely the same trend measurement, which is the redundancy the report itself warns about.
- Caveat: each removal changes only 1–5 trades. This says the extra factors are **unproven**, not that a leaner version would be profitable. A lean version (volume + HTF + the hard filters) is a new hypothesis and must be tested on *new* data, not on this data.

## 4. Optimisation (3 parameters, 45 combinations)
Grid:
- Score threshold: preset −10 / −5 / 0 / +5 / +10.
- RVOL threshold: ×0.8 / ×1.0 / ×1.2.
- Breakout length:
  - 5m: 4 / 6 / 8 bars.
  - 15m: 3 / 4 / 5 bars.

Results:
- **All 45 combinations are negative in-sample**, on the pooled four runs.
- Not one combination is positive on all four instrument/TF runs.
- The best in-sample result is −0.18R; the base ranks 23rd of 45.
- The pattern is smooth and consistent: **stricter = less negative**.
  - Loosest (score −10, RVOL ×0.8): −0.39R in-sample, −0.23R out-of-sample.
  - Strictest (score +10, RVOL ×1.2): −0.18R in-sample, +0.01R out-of-sample.
- Breakout length shows no consistent effect, so keep the preset.

**Change that holds out-of-sample: raise the score threshold by 10 and the RVOL threshold by 20%.**

| TF | Min score | RVOL threshold |
|---|---|---|
| 5m | 75 (was 65) | 1.8 (was 1.5) |
| 15m | 70 (was 60) | 1.56 (was 1.3) |

- With these settings, gross R is +0.13 and net R is −0.13 (95% CI −0.37 to +0.10, n71).
- It **reduces losses and does not create an edge**.
- Set it with the existing inputs "Min score override" and "RVOL threshold override". The code defaults are left at the report's values.

## 5. What would have to change for an edge to be possible
1. **Costs dominate.** A system that makes about +0.1R gross can't pay about 0.3R of costs.
   - Fewer, larger trades are needed, so that R is large relative to the ~15 Nifty points (~₹965/lot) a round trip costs.
   - The 15m chart costs less in R than 5m: 0.24R vs 0.49R on Nifty.
   - Do not move to 1m.
2. **The targets don't fit the intraday window.** Only 5 of 98 trades reached 3R, and 44% were cut at 15:15. Shorter targets (T3 = 2R) or earlier entries would be a new hypothesis to test forward, not something to fit to this data.
3. **More data is the cheapest improvement.**
   - TradingView Premium's Deep Backtesting, or broker historical data via Phase 4, would give 2–3 years.
   - That is enough to reach the 200-trade bar and run a real walk-forward test.

## Bottom line
- **5m (NIFTY, BANKNIFTY):** negative after costs; reject.
- **15m NIFTY:** negative after costs.
- **15m BANKNIFTY:** break-even after costs, unproven (n = 31).
- **Use the indicator only as a discretionary / alert tool**, with the stricter thresholds. Paper-trade it forward, log every alert's real fill, and re-test once there are 200+ signals.
- **Do not enable automated order placement.**
