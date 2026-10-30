# R4 — range-calibrated targets: protocol (20 Oct 2026, ~01:40 IST, before the live-feasible model was trained)

## Part A: the live-feasible range model must re-earn its pass
The validated model (`ml_result.md`) uses breadth features from all 50 stocks, too fragile to fetch live. The live model drops the breadth, VWAP and relative-volume features and keeps what the bridge can compute from the index's own 5m bars, India VIX and the calendar:

`r1, r3, r6, r12, r24, r_open, gap, first30, rng_atr, atr_px, rv12, rv_prev, tod, dow, expiry, vix, vix5, vix_open, is_index` (19 features)

| | |
|---|---|
| **Models** | histogram gradient boosting with quantile loss at 0.10, 0.50 and 0.90, plus a point model (squared loss) for R²; depth 6, 300 trees, learning rate 0.05 |
| **Training rows** | all 52 symbols, 2022–2024 |
| **Validation** | 2025, indices only. Pass: R² ≥ 0.30 on log range and 10–90% coverage between 75% and 85% |
| **Final** | Jan–Jul 2026, indices only, run once with the same bars |
| **If it fails either stage** | R4 is not built into the live system |
| **Production model, if both pass** | refit on all data (2022 – Jul 2026), same settings; saved with feature list, library versions and SHA-256 |

## Part B: the live paper experiment R4
**Forecast:** for an alert at time t, the forecast uses the last *completed* 5m bar of the alert's index. It gives three next-60-minute ranges in points: L10, M50 and U90, computed as exp(quantile) × price.

**Book `r4`:** it opens **only when the executable book opens**, at the same entry price and with the same stop, breakeven and trail rules, the same 15:15 square-off, and the same fills (bid/ask touch, one-tick trade-through, SL-M stops). **Only the targets differ:**

| Target | Rule |
|---|---|
| T1 (40%) | entry ± 0.5 × M50 |
| T2 (30%) | entry ± 0.5 × U90 |
| T3 (30%) | entry ± U90 |

If T1 would sit at or inside one tick of the entry, or the targets are not in order, the trade is recorded as rejected (`r4: degenerate targets`) and excluded from the comparison. No forecast (data missing or stale) means a rejection with that reason.

**Comparison:** paired by signal id, using closed trades in both `executable` and `r4`. Per pair, Δ = net R(r4) − net R(executable). R is the signal's own risk (entry − stop), so both books share one unit.

**Pass:**
1. mean Δ ≥ +0.05R;
2. one-sided paired t-test p < 0.0125 (R4 is the 4th registered experiment: 0.05 / 4);
3. at least 100 paired trades.

INCONCLUSIVE below 100 pairs. FAIL otherwise. A PASS means "range-calibrated targets beat fixed targets on paper", not that either is profitable.

**Frozen files:** listed with SHA-256 in `REGISTRY.md` under R4 once the code exists, before the first live session.

## Amendment, 20 Oct 2026, review round 3 (before any live data)
1. **Model:** `models/range_r4.pkl` is now **M1**: the same architecture fitted on 2022–2025 and conformalised on Jan–Jul 2026. It was adopted by the rule pre-declared in `range_benchmark_protocol.md` (`range_benchmark_result.md`). Targets keep the same mapping (T1 = ±0.5·M50, T2 = ±0.5·U90, T3 = ±U90).
2. **Paired shadow trials:** an `r4` trade is opened for every executable entry and may still be open when the next one starts. These are independent paired trials of target choice, not one strategy's positions.
3. **Statistics:** the paired test runs on **day means** of Δ, at α = 0.05 / 4 (R1–R4 share one family). It is judged once, when 100 pairs are reached. Both books' absolute net R are reported next to the verdict, and a relative PASS with losing books is not a reason to trade.
4. **Quantity:** both books trade 10 whole lots (4/3/3 at T1/T2/T3) and pay fees for them.
