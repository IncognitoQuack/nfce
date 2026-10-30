# NFCE — real-data robustness test (18 Oct 2026, no API keys needed)

> **Corrected in v2 (PHASE7_V2_EVIDENCE.md §B and §E).**
> - **Noise:** "±2 points" below was unbounded Gaussian noise (σ = 2 on each price). The bounded redesign shows ±2 points replaces about a third of NIFTY signals, not half.
> - **BANKNIFTY:** it ran with the NIFTY instrument setting (now −0.30R, was −0.32R).
> - **"Stricter defaults":** these were chosen after seeing out-of-sample results.
>
> The conclusion stands.

## Short answer
The system is **not robust and not profitable** on this real data either.

- Every variant is negative after costs: −0.21R to −0.32R per trade.
- On Nifty, tiny price differences change about half of the signals.
- No threshold setting, changed by ±20%, turns it positive.

This independent check agrees with Phases 2–3. **Do not trade it with real money.** No amount of re-tuning on this data would change that honestly. It would only fit the past.

## Data
- Yahoo Finance 5-minute bars, 23 Jul – 16 Oct 2026, the free maximum of ~60 days. The first 14 days are used for indicator warm-up.
- NIFTY 50 and NIFTY BANK **spot** index, India VIX, and the heavyweight stocks.
- **Volume proxy:** spot indices have no volume, so the summed volume of the 5 heavyweights stands in for futures volume.
- **Not used:** futures OI (not available). The OI factor drops out and the score renormalises, exactly as the Pine code does when OI is n/a.
- Tools: `nfce_engine/tools/fetch_yahoo.py` and `nfce_engine/tools/robustness.py`.

## 1. Results on real data (net of the same costs as Phases 2–3)
| Run | Trades | Win (net) | Avg R gross | Avg R net | Net ₹/lot |
|---|---|---|---|---|---|
| NIFTY 5m, report defaults | 17 | 35% | +0.31 | **−0.25** | −5,098 |
| NIFTY 5m, stricter defaults | 12 | 42% | +0.31 | **−0.26** | −3,806 |
| BANKNIFTY 5m, report defaults | 14 | 36% | +0.08 | **−0.32** | −3,163 |
| BANKNIFTY 5m, stricter defaults | 12 | 50% | +0.14 | **−0.21** | −935 |

- The gross edge (+0.1 to +0.3R) is again smaller than costs (~0.4–0.5R per trade on 5m).
- The samples are small (12–17 trades). This is a consistency check, not proof on its own.

## 2. Does it match TradingView's futures results?
On the same weeks, only 0–1 of TradingView's 12 NIFTY futures signals appear exactly in the spot-data run. Bar-by-bar tracing (`run(..., trace=...)`) shows why:

- **Where spot and futures behave alike, the engine agrees.** It fires on the same trades (27, 29 and 31 Jul, 26 Aug), with scores 84/76/77/83 vs TradingView's 92/86/76/80. The gap in scores is the missing OI factor.
- **Elsewhere, signals die on hair-thin margins:**
  - candle body 0.46–0.48 ATR vs the 0.50 rule;
  - risk 2.06–2.87 ATR vs the 2.0 cap;
  - room to the next level just under 1R, because VWAP is built from a different volume series;
  - and then "already in a trade" knock-on effects.

So the differences come from the inputs (spot vs futures prices, proxy volume), not from a coding error. **The free spot+proxy route would therefore test a *different* system**, not the TradingView one.

## 3. Noise test: how fragile are the signals?
Tiny random noise was added to every price, 20 runs per level. How many baseline signals survive:

| | ±0.5 point | ±2 points |
|---|---|---|
| NIFTY (index ~24,000) | 86–87% | **50–53%** (worst run 25–29%) |
| BANKNIFTY (index ~55,000) | 95–98% | 82–87% |

- On Nifty, noise of ±2 points (less than 0.01%, smaller than the spot–futures difference) **changes about half of the trades**.
- A robust edge should not depend on which data vendor's last tick you see.
- With noise, average net R ranged from −0.83 to +0.07 on Nifty: essentially luck, centred below zero.

## 4. Parameter test (stricter defaults, each threshold ×0.8 / ×1.2)

| Threshold | NIFTY ×0.8 | NIFTY ×1.0 | NIFTY ×1.2 | BANKNIFTY ×0.8 | BANKNIFTY ×1.0 | BANKNIFTY ×1.2 |
|---|---|---|---|---|---|---|
| Body (× ATR) | −0.44 | −0.26 | −0.26 | −0.21 | −0.21 | −0.20 |
| Max risk (× ATR) | −0.41 | −0.26 | −0.31 | −0.84 (n2) | −0.21 | −0.28 |
| Room (× R) | −0.45 | −0.26 | −0.15 | −0.30 | −0.21 | −0.10 |
| Chop max | −0.47 | −0.26 | −0.26 | −0.16 | −0.21 | −0.21 |
| SL buffer | −0.27 | −0.26 | −0.01 | −0.30 | −0.21 | −0.32 |

**All 30 settings are negative.** The "best" cells (room ×1.2, SL buffer ×1.2 on Nifty) come from 11–12 trades and would be curve-fitting if adopted.

## What this means
1. **The idea is not robust.** It's a breakout + many-indicator score with sharp thresholds, so small data changes flip trades. Adding more filters makes this worse, not better.
2. **There's a small gross edge, but costs exceed it.** It's about +0.1–0.3R per trade before costs, about −0.2 to −0.3R after. That holds in all three independent checks: TradingView futures (Phases 2–3), Yahoo spot Nifty, and Yahoo spot Bank Nifty.
3. **Optimising further on ~100 trades would be curve-fitting.** It would look good in a backtest and fail live.

## Honest options from here
- **A. Keep it as a discretionary context tool, not a signal generator.** The dashboard (VWAP, OI build-up, levels, VIX) is useful for reading the market. Don't follow its BUY/SELL labels blindly.
- **B. Test a different, simpler hypothesis on years of data.** For example, opening-range breakout on 15m with one volume filter. Few rules means less fragility. It needs real multi-year data: Upstox (spot from 2022, free) for a spot-based version, or TradingView Premium Deep Backtesting for futures.
- **C. Paper-trade with the bridge for 2–3 months.** Log every signal and its real fill. If, after 200+ signals, net R is clearly positive, revisit. My expectation, based on all evidence so far, is that it won't be.

No configuration of this tool, or any other, will be "profit in every case". The goal of testing is to find out whether an edge exists *before* risking money. For this tool, the answer so far is no.
