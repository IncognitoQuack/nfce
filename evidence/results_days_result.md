# Results days and the stock 3m signals: result (23 Oct 2026, evening)

**Protocol:** `results_days_protocol.md`, SHA-256 `b660c95b23eaed4f858ebc28bed123b2bd6ca0f96075fd89e5c4d76e0dd2370e`, registered at 15:47 before the join.
**Code:** `nfce_engine/tools/results_days.py`.
**Calendar:** NSE board meetings 2022-01 → 2026-10 (46,346; 40,252 about results; 211/213 F&O stocks).

## Train 2022–24 (16,598 trades; 785 in results windows)
| Exits | Window | n | Win % | Net R | SD of net R | ₹ (1 lot) |
|---|---|---|---|---|---|---|
| V0 (live) | **Results day or the next day** | 785 | 52.5 | **−0.170** | 0.983 | −4.4 L |
| V0 | Other days | 15,813 | 51.5 | −0.275 | 0.998 | −89.5 L |
| K4 | **Results day or the next day** | 785 | 50.8 | **+0.010** | 0.657 | +0.25 L |
| K4 | Other days | 15,813 | 46.5 | −0.036 | 0.631 | −29.2 L |

**H_R** (results-window trades do worse): **fails** for both. The difference is in the other direction:
- V0: +0.105R (p "not worse" 0.997);
- K4: +0.045R (p 0.956).

So no skip rule; validation is not needed for a rule that is not adopted.

## Use
- **Live:** stock and scanner alerts carry a 📰 flag (results today / yesterday / next trading day). It is information for a person: the moves are bigger and faster, and a gap after the announcement can jump a stop.
- **A new lead, NOT a finding:** the results windows did better here, and K4 was even slightly positive.
  - This was not the registered hypothesis, and it rests on 785 trades.
  - It would need its own registered test (train → 2025 → 2026) before any use.

## Confirmation test of the lead (`results_k4_protocol.md`, SHA-256 `59dd10e46f1a83b1fdb1a9b6d1fbfffa0e5e0f95194c4cb623c8090012a6c272`, registered 17:36 before the look): FAIL
| 2025, K4 exits | n | Days | Win % | Gross R | **Net R** | Day-block 95% | p(day) | PF | ₹ (1 lot) |
|---|---|---|---|---|---|---|---|---|---|
| **Results windows (test)** | 337 | 96 | 51.6 | +0.041 | **−0.021** | −0.085..+0.037 | 0.962 | 1.02 | +0.22 L |
| Other days (reference) | 6,575 | 249 | 45.4 | +0.040 | −0.046 | −0.073..−0.019 | 1.000 | 0.85 | −25.8 L |

- **Results windows again beat other days** (2022–24 and 2025 alike), but they are not profitable after costs: the interval includes 0.
- **The lead is closed** under the protocol: no RES4 account; 2026 is not looked at.
- **What stays:** the 📰 flag stays as information.
