# Two leads from 21–22 Oct: results

**Protocol:** `leads_2day_protocol.md`, SHA-256 `10cc3f993849d56ccd620bfee3520cbc3d006d93576288fcabb8cb940ade616d`, registered 15:59 on 22 Oct before any run.
**Code:** `nfce_engine/tools/leads_2day.py`.

## H2: scanner, SELL side only. Train 2022–24, 50 stocks, 5m, current costs: FAIL
**Reproduction check:** G1 10:15, both sides, gives 7,135 trades at −0.069R, the same as `scanner_result.md`.

| Scan | Side | Trades | Win % | Gross R | **Net R** | Day-block 95% | PF |
|---|---|---|---|---|---|---|---|
| 10:15 | BUY | 3,581 | 44.2 | −0.012 | −0.100 | −0.137..−0.064 | 0.78 |
| 10:15 | SELL | 3,554 | 49.4 | +0.048 | **−0.038** | −0.075..−0.002 | 0.94 |
| 11:15 | BUY | 3,590 | 44.5 | +0.004 | −0.084 | −0.118..−0.051 | 0.80 |
| 11:15 | SELL | 3,568 | 47.4 | +0.029 | **−0.056** | −0.089..−0.022 | 0.85 |
| 13:15 | BUY | 3,585 | 45.4 | +0.044 | −0.044 | −0.071..−0.016 | 0.87 |
| 13:15 | SELL | 3,586 | 41.5 | −0.017 | **−0.101** | −0.128..−0.074 | 0.62 |
| **Pooled** | **SELL** | **10,708** | 46.1 | +0.020 | **−0.065** | −0.093..−0.037 | 0.82 |

- **SELL beats BUY in the morning** (10:15, 11:15): a small gross edge (+0.03 to +0.05R), but costs turn every row negative.
- **The 13:15 SELL scan, the only one paper-traded live today, is the worst row** (−0.101R).
- **What happened live:** selling the losers made money on both live days because both days had a falling stretch. Over 3 years it loses after costs. **Nothing changes live.**

## H1: stock 3m, morning entries only. Train 2022–24, 210 F&O stocks (159 never used before), current costs: FAIL
| Trades | n | Win % | Gross R | **Net R** | Day-block 95% | PF |
|---|---|---|---|---|---|---|
| All day, all stocks | 16,598 | 51.5 | +0.051 | −0.270 | −0.290..−0.249 | 0.66 |
| **H1: before 12:00** | 8,508 | 52.3 | +0.051 | **−0.224** | −0.251..−0.197 | 0.72 |
| 12:00 and later | 8,090 | 50.7 | +0.051 | −0.318 | −0.343..−0.292 | 0.58 |
| All day, new stocks only | 12,138 | 51.8 | +0.055 | −0.244 | −0.268..−0.222 | 0.69 |
| Before 12:00, new stocks only | 6,194 | 52.2 | +0.048 | −0.206 | −0.238..−0.175 | 0.74 |

- **Morning vs afternoon:** mornings lose less, but they lose.
- **Same edge before costs:** +0.051R, morning and afternoon alike. The afternoon's extra loss is cost, not worse signals.
- **The 2-day pattern** (morning +0.2R) was the market of those 2 days.
- **The 159 never-used stocks** behave like the original 50, so the old result was not a small-sample accident.
- **Nothing changes live.**
