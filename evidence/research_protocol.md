# Multi-year research protocol (written 20 Oct 2026, ~01:00 IST, before any result on this data)

## Data
- **Source:** Upstox v3 historical 5-minute candles, 3 Jan 2022 – 31 Jul 2026 (1,135 sessions each) for NIFTY, BANKNIFTY, India VIX, and the heavyweights HDFCBANK, ICICIBANK, RELIANCE, INFY, BHARTIARTL, SBIN, KOTAKBANK and AXISBANK.
- **Not used before by this project:** all earlier tests used 24 Jul – 19 Oct 2026.
- **Spot index prices** are traded as a proxy for futures. Index candles carry no volume, so volume = the summed volume of the index's five heavyweights (the same proxy as Phase 5).
- **Stock candles may be unadjusted** for splits; they are used only for volume and day-direction.

## Time splits (fixed now)
| Split | Period | Use |
|---|---|---|
| TRAIN | 2022-01-03 – 2024-12-31 | All exploration; walk-forward by calendar year (2022, 2023, 2024) |
| VALIDATION | 2025-01-01 – 2025-12-31 | Choose among the train survivors |
| FINAL TEST | 2026-01-01 – 2026-07-31 | Touched **once**, only for the design(s) passing validation |

## Costs (all candidates)
- **Fees:** the dated futures fee schedule (`nfce/costs.py`, by trade date).
- **Size:** 1 lot (NIFTY 65 / BANKNIFTY 30 units, current lot sizes); per-unit costs are lot-neutral.
- **Orders:** NFCE 40/30/30 = 4 orders; single-exit designs = 2.
- **Friction:** 4 ticks per side (NIFTY 0.1, BANKNIFTY 0.2).

## Expiry calendar (historical)
For NFCE expiry filters; the previous session if the day was a holiday.
- **NIFTY:** weekly Thursday until 31 Aug 2025, weekly Tuesday from 1 Sep 2025.
- **BANKNIFTY:**
  - weekly Thursday until 3 Sep 2023;
  - weekly Wednesday from 4 Sep 2023 to 13 Nov 2024;
  - then monthly only, on the last Thursday until Aug 2025 and the last Tuesday from Sep 2025.

## Candidates (complete list; nothing is added after results are seen)
All are run on NIFTY and BANKNIFTY separately; 5m bars unless stated.

**N: NFCE engine, on 5m and 15m:**
| ID | Rule |
|---|---|
| N0 | v2 defaults |
| N1 | Entries until 11:15 |
| N2 | N1 + single exit at 2R |
| N3 | N1 + `min_risk_pct` 0.25 |
| N4 | Score threshold +10 |
| N5 | Volume surge as a hard filter |

**O: Opening-range breakout** (literature: Zarattini & Aziz 2023):
- **Range:** the first 15, 30 or 60 minutes.
- **Entry:** the first 5m close beyond the range, before 13:00; one trade a day.
- **Stop:** the opposite side of the range ("opp") or the range midpoint ("mid").
- **Exit:** the 15:20 close ("eod") or a 2R target ("2R").
- **Filter:** none, or the range between 0.25 and 0.60 × the daily ATR14 of previous days ("volgate").
- **Total:** 3 × 2 × 2 × 2 = 24 per index.

**M: First-hour momentum** (Gao, Han, Li & Zhou 2018):
- **Signal:** the sign of the 09:15→10:15 return.
- **Trade:** in that direction from {14:30, 15:00} to the 15:25 close.
- **Filter:** all days, or |return| > the median of the previous 60 sessions.
- **Total:** 4 per index.

**V: VWAP trend:**
- **Entry:** at the 10:15 bar close, long if close > session VWAP and EMA20 > EMA50 (5m); short mirror.
- **Stop:** {1.5, 3.0} × ATR14 (5m). Exit at 15:20.
- **Total:** 2 per index.

**Total:** 24 (N) + 48 (O) + 8 (M) + 4 (V) = **84 configurations**.

## Selection
1. **TRAIN survivors** must meet all of these:
   - ≥ 100 train trades;
   - pooled train net R > 0;
   - net R > 0 in at least 2 of the 3 train years.
2. **VALIDATION:** of the survivors, keep those with 2025 net R > 0 **and** a one-sided t p < 0.05 (day-clustered, i.e. on daily mean R) on ≥ 40 trades. Carry at most the top 3 by 2025 net R to the final test.
3. **FINAL TEST (Jan–Jul 2026)** for each carried design. It **passes** only if all of these hold:
   - net R > 0;
   - day-block 95% interval lower bound > 0;
   - profit factor ≥ 1.15;
   - ≥ 40 trades.
4. **Multiple testing:** 84 configurations were screened. A final-test pass therefore becomes a candidate for **registered live paper testing**, not a trading recommendation.
5. **If nothing survives a stage, the process stops there and that is the result.**

## Software hardening, run alongside
- **Fuzz:** randomised tests of every alert payload and command.
- **Failure injection:** provider timeouts and errors, Telegram failures, a database restart mid-trade, clock jumps.
- **End-to-end dry run** at the next market open.
