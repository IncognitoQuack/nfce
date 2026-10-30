# Phase 7: v2 evidence rebuild (18 Oct 2026)

Every number below was produced by the v2 code after the fixes listed in `CHANGELOG.md`. Costs are the **dated
schedule** (the fees in force on each trade's date, `nfce_engine/nfce/costs.py`), with the **current-cost stress**
(the 18 Oct 2026 schedule applied to every trade) shown next to it. Both include 4 ticks of friction per side. Every
p-value is two-sided. "Significant" means the result survives Holm correction within its family.

**Bottom line: v2 changes no conclusion.** No configuration shows a net edge after costs that can be told apart
from zero. The fixes made the evidence more trustworthy; they did not make the system profitable.

## A. NFCE on TradingView futures (strategy v2, script version 3)
- **Data:** TradingView continuous futures NSE:NIFTY1! and NSE:BANKNIFTY1!. This account's plan gives about 5,000 bars,
  so 5m covers 13 Jul – 16 Oct 2026 and 15m covers 1 Dec 2025 – 16 Oct 2026.
- **Settings:** all v2 defaults, Instrument = Auto (resolved to the chart), heavyweights = the instrument's default list, 10 lots.
- **Raw trades:** `evidence/tv_v2_base_trades.txt`, copied from the Pine Logs.
- **Re-check:** recomputed independently by `nfce_engine/tools/tv_evidence.py`, which agrees with the in-browser script `nfce_analysis_v2.js`.

| Config | Trades (days) | Win % net | Gross R | Cost R | Net R dated [day-block 95%] | Net R current | t | p | Holm (4) |
|---|---|---|---|---|---|---|---|---|---|
| BANKNIFTY 5m | 10 (10) | 30 | −0.150 | 0.435 | **−0.586** [−1.14, −0.01] | −0.586 | −1.93 | 0.09 | no |
| BANKNIFTY 15m | 29 (29) | 62 | +0.253 | 0.146 | **+0.107** [−0.24, +0.46] | +0.058 | +0.60 | 0.55 | no |
| NIFTY 15m | 36 (36) | 42 | +0.055 | 0.189 | **−0.135** [−0.43, +0.19] | −0.173 | −0.86 | 0.40 | no |
| NIFTY 5m | 19 (19) | 42 | +0.006 | 0.461 | **−0.455** [−0.95, +0.07] | −0.455 | −1.71 | 0.11 | no |
| **Pooled** | 94 | — | +0.084 | — | **−0.173** [−0.39, +0.04] | — | −1.66 | 0.10 | — |

- **Reconciliation:** the TradingView broker emulator matched the state machine on every bar. The counters
  mmStateFlat, mmEmuFlat and mmQty are 0/0/0 in all four runs; mmQty is the new v2 check of the remaining contracts
  after T1 and T2.
- **Costs dominate on 5m.** About 0.44–0.46R of every 5m trade goes to costs; on 15m it is 0.15–0.19R.
- **The only positive configuration is BANKNIFTY 15m,** and it is a coin flip (p = 0.55, 29 trades). v1 got +0.04R
  on the same configuration. Picking it out of four would be selection, not evidence.
- **Ablation:** switching off any one factor moves net R by ±0.0–0.25R. On 15m most factors change nothing at all,
  because the same few trades pass either way. The "volume hard filter" variant leaves 2–5 trades, which is too few to read.
- **Parameter grid (cells with at least 10 trades):** 0 of 25–45 cells are positive on BANKNIFTY 5m, NIFTY 5m and NIFTY 15m. On BANKNIFTY 15m,
  42 of 45 cells are positive. That cluster rests on the same ~29 correlated trades, and the best cell is +0.13R.
  It is not an independent confirmation.

## B. NFCE on Yahoo spot data (5m, 23 Jul – 16 Oct 2026; first 14 days warm-up)
`nfce_engine/tools/robustness.py`, 20 seeds per perturbation. Spot indices carry no volume, so the summed volume of
the instrument's five heavyweights is the proxy. There is no OI on spot data.

| Index | Trades | Gross R | Net R dated [day-block] | p |
|---|---|---|---|---|
| NIFTY | 17 | +0.307 | −0.243 [−0.73, +0.24] | 0.33 |
| BANKNIFTY (now with instrument = BANKNIFTY, fix H06) | 14 | +0.079 | −0.304 [−0.74, +0.17] | 0.25 |

**Noise test (redesigned, review M09).** Perturbations are now bounded and on the tick grid.
- **shift:** all four prices of a bar move together, so candle shape is unchanged.
- **jitter:** the four prices move independently, then high/low are repaired. This widens ranges, and the table shows by how much.

Similarity to the baseline signals is measured as precision / recall / Jaccard (J).

| Perturbation | NIFTY range change | NIFTY P / R / J | NIFTY net R mean [min..max] | BANKNIFTY P / R / J | BANKNIFTY net R mean |
|---|---|---|---|---|---|
| shift ±1 tick | 0 | 0.98 / 0.96 / 0.94 | −0.21 [−0.37, −0.07] | 0.97 / 0.96 / 0.94 | −0.39 |
| shift ±5 ticks | 0 | 0.97 / 0.92 / 0.89 | −0.21 [−0.35, −0.07] | 0.95 / 0.96 / 0.91 | −0.41 |
| shift ±20 ticks (±2 / ±4 pts) | 0 | 0.81 / 0.74 / **0.63** | −0.31 [−0.56, −0.05] | 0.87 / 0.85 / 0.76 | −0.50 |
| jitter ±1 tick | +0.01 pt | 0.96 / 0.97 / 0.93 | −0.26 | 0.97 / 0.99 / 0.96 | −0.36 |
| jitter ±5 ticks | +0.04 pt | 0.92 / 0.89 / 0.82 | −0.26 | 0.95 / 0.97 / 0.93 | −0.39 |
| jitter ±20 ticks | +0.30 pt | 0.76 / 0.67 / **0.56** | −0.38 [−0.57, −0.18] | 0.87 / 0.88 / 0.78 | −0.43 |

- Allowing a signal to arrive one bar late (timing tolerance 1) changes nothing. Perturbed signals do not shift in time; they appear or vanish.
- On NIFTY, a bounded ±2-point move (under 0.01% of the index) replaces about a third of the signals. The earlier
  "about half" figure (Phase 5) came from unbounded Gaussian noise, so it overstated this a little. The conclusion stands: the signal set depends on sub-tick details.
- Net R stays negative in every perturbation, every seed and both indices.

**Parameters ×0.8 / ×1.2:**
- NIFTY: 0 of 12 changed cells are positive.
- BANKNIFTY: 0 of 12 are positive.
- The least-bad cell (NIFTY SL buffer ×1.2, −0.08R on 17 trades) would be curve-fitting if adopted.

## C. Simple pre-registered ideas on 60m spot data (Yahoo, 2 Nov 2023 – 16 Oct 2026)
`nfce_engine/tools/simple_ideas.py`.
- **Data:** 727 sessions per index (Yahoo's ~730-calendar-day maximum for 60m bars), file hashes in `data/yahoo/MANIFEST.json`.
- **Exclusions:** three short sessions (2025-10-21 Muhurat, 2026-01-13, 2026-04-20) are kept and handled causally.
- **Trading:** one lot, two orders per trade.

| Hypothesis | Index | n | Gross pts | Net pts dated [week-block] | t | Net pts current | v1 report (legacy) |
|---|---|---|---|---|---|---|---|
| H1 ORB, stop = other side | NIFTY | 544 | +6.6 | −2.1 [−9.0, +4.8] | −0.52 | −8.4 | −8.5 |
| H1 ORB, stop = mid | NIFTY | 544 | +8.3 | −0.4 [−6.8, +6.0] | −0.11 | −6.7 | −6.8 |
| H2 momentum, all | NIFTY | 722 | −0.6 | **−9.2** [−14.0, −4.5] | **−4.12** | −15.6 | −15.7 |
| H2 momentum, big | NIFTY | 283 | +1.5 | −6.7 [−14.3, +0.9] | −1.80 | −13.5 | −12.9 |
| H1 ORB, stop = other side | BANKNIFTY | 533 | −1.3 | −20.7 [−41.9, +0.8] | −1.93 | −34.6 | −34.8 |
| H1 ORB, stop = mid | BANKNIFTY | 533 | +2.5 | −16.9 [−36.8, +3.7] | −1.71 | −30.7 | −31.0 |
| H2 momentum, all | BANKNIFTY | 722 | +3.8 | −15.4 [−27.5, −3.4] | −2.54 | −29.4 | −30.0 |
| H2 momentum, big | BANKNIFTY | 280 | +0.6 | −17.8 [−36.3, +0.7] | −1.82 | −32.3 | −31.3 |

- **None of the 8 is positive after dated costs.**
- **One result survives Holm, and it is negative:** NIFTY H2 momentum (all days) **loses money** significantly. The other seven are not significantly different from zero after historical costs.
- **Costs explain most of the difference from v1.** Before April 2026, STT on futures was 0.0125–0.02%, against 0.05% now. A NIFTY round trip cost ≈8.7 points on average at historical rates, against ≈15 at today's.
- **The trade counts moved slightly** (722 vs 724, 283 vs 285) because v2 no longer uses a previous session that lacks its 15:15 bar, a rule that is causal.

## D. Paper ledger replay
`nfce_engine/tools/paper_replay.py` was rewritten for the v2 bridge API; the v1 script called methods that no longer exist.
- **What it does:** every engine signal on the 60-day Yahoo 5m data opens a theoretical paper trade. Bars are then fed as quotes in adverse-first order.
- **NIFTY:** 20/20 trades identical in gross R.
- **BANKNIFTY:** 19/19 identical.
- **Not shown:** this proves only that the ledger and the engine implement the same rules. Executable fills (bid/ask, delay, spread, rejects) can only be measured live.

## D2. Bar-by-bar parity: Python engine = TradingView (golden export)
**Inputs:** the strategy's golden export logged 5,000 bars per chart, from TradingView Pine Logs downloaded with the owner's permission. The logs hold:
- OHLCV, futures OI, India VIX, the heavyweights' day changes and the daily levels;
- TradingView's own indicator values, signal and position on every bar.

**Method:** `nfce_engine/tools/golden_parity.py` feeds the engine exactly those inputs and compares every bar after 15 warm-up sessions. The export starts mid-history, so recursive indicators need time to converge.

| Chart | Bars compared | Indicators | Signals TV / engine / identical | Position path | Trades |
|---|---|---|---|---|---|
| NIFTY1! 5m (15 Jul – 16 Oct 2026) | 3,927 | 19 of 20 fields 100.00%; VIX change 99.6% (see below) | 13 / 13 / **13** | **100%** of bars | identical entry, R, P&L, exit |
| BANKNIFTY1! 15m (30 Dec 2025 – 16 Oct 2026) | 4,628 | 19 of 20 fields 100.00%; VIX change 99.9% | 25 / 25 / **25** | **100%** of bars | identical |

Parity was not perfect on the first run. It found two real engine differences, both now fixed with tests:
1. **+DM ties.** When the up-move and the down-move were equal (e.g. +5.7 / −5.7 points), float rounding made the engine count a +DM; TradingView counts neither. This affected +DI/ADX on 2.5% of bars. Fixed with a tolerance far below one tick (`ta.dmi`; `test_dmi_equal_up_and_down_moves_…`).
2. **Previous-day levels.** TradingView takes them from the symbol's daily bars, whose futures close is the official settlement; the engine rebuilt them from the last intraday bar. PDC differed on 70% of days, by up to 32 points. This changed 2 of 13 NIFTY signals through the "room to the next level" check. Fixed: `prepare(daily=...)` (`test_previous_day_levels_come_from_daily_bars_when_given`).

**Remaining:** a 0.1–0.4% VIX-change mismatch. It is an input-reconstruction limit, not an engine difference. The export records VIX on chart bars, so VIX's own bars (which `close[5]` counts) must be inferred, which is ambiguous when VIX really repeats a value. No signal depends on it.

Neither fix changes any number in sections B–D (re-run, outputs identical). Outputs: `evidence/golden_parity_*.txt`.

## E. Corrections to earlier reports
1. **PHASE6 "all 8 variants lose money after costs over 3 years ... so this is not bad luck"** is overstated.
   - Those costs were the 2026 schedule applied to 2023–2026 trades, a stress test and not historical P&L (review H08).
   - At historical costs, 7 of 8 are not significantly different from zero. The defensible statement is "none shows a positive edge; one is significantly negative".
   - "3 years" means 727 sessions (2 Nov 2023 – 16 Oct 2026); the tool asked Yahoo for "730d".
2. **PHASE5 "±2 points noise"** was unbounded Gaussian noise with σ = 2 points on each of O/H/L/C (review M09). See B for the bounded redesign.
3. **PHASE5 BANKNIFTY ran with the NIFTY instrument setting** (review H06), which applied weekly-expiry rules to Bank Nifty. Corrected: −0.30R (was −0.32R).
4. **PHASE3 "stricter defaults" were chosen after seeing out-of-sample results** (review F-03/M02). v2 restores the spec presets; the stricter values are only a labelled option (`strict_phase3`).
5. **The v1 Pine Instrument input defaulted to NIFTY on every chart** (found in this phase). On a BANKNIFTY chart that used Nifty's expiry days and heavyweights unless changed by hand. The v1 BANKNIFTY TradingView runs had it set by hand. v2 adds Instrument = Auto.
6. **H-A's opening-volume gate passed vacuously on bars with no volume** (0 ≥ 1.5 × 0). It was never run on real data, so no result changes. v2 refuses to run it without volume.

## F. What would change the conclusion
Only new, independent data tested under rules fixed in advance: see `REGISTRY.md` (R1–R3). Re-tuning NFCE on the
data above would not count.
