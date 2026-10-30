# Day-level profit booking: result (25 Oct 2026, evening)

**Protocol:** `day_rules_protocol.md`, SHA-256 `0f9c6573d4643e1a925b8d50144fcb3a85ebfe315bb8b91d53e41f3dc26ce7a3`, registered at 17:31 before the run.
**Code:** `nfce_engine/tools/day_rules.py`. The simulator was checked on a hand-made 23-Oct-like day (base +0.5R, DT +3.5R, DG +1.5R, as calculated). The trades come from a fresh engine run that also records exit times (`stock3m_research.trades`, exit_time added; no rule changed; engine tests 108 pass).
**Data:** 210 F&O stocks, 3m, current costs. One unit = 1R per trade; the day total is the sum over the trades taken.

## Train 2022–24 (739 days)
| Rule × exits | Mean day: base → rule | Difference | p | Days changed | Verdict |
|---|---|---|---|---|---|
| DT (stop at +3R) × V0 | −6.054 → −5.320R | +0.734 | <0.0001 | 141 | risk control only |
| **DG (give back half after +2R) × V0** | −6.054 → **−5.001R** | **+1.053** | <0.0001 | 202 | risk control only |
| DT × K4 | −0.754 → −0.678R | +0.077 | 0.0018 | 108 | risk control only |
| DG × K4 | −0.754 → −0.737R | +0.018 | 0.021 | 19 | FAIL |

## Validation 2025 (249 days, one look; the three that passed train)
| Rule × exits | Mean day: base → rule | Difference | p | Verdict |
|---|---|---|---|---|
| DT × V0 | −8.704 → −7.493R | +1.211 | <0.0001 | risk control only |
| **DG × V0** | −8.704 → **−7.150R** | **+1.554** | <0.0001 | **risk control only, held on unseen data** |
| DT × K4 | −1.256 → −1.127R | +0.128 | 0.063 | FAIL |

The worst day is unchanged everywhere: the worst days never reach +2R / +3R, so the rules never trigger on them.

## What it means
- **Stopping new trades after a good morning that starts to give back (DG)** reliably reduces losses for the exits the live accounts use (V0), on 2022–24 and again on 2025.
- **It is not a profit rule:** the days stay negative on average, because the signals themselves lose after costs.
- **It does not protect the worst days**, which go wrong from the start.
- **Under the protocol, this goes to the owner to decide:**
  - **Adopt** DG as a risk control in the paper accounts. Once an account's day P&L has reached +2 × its risk-per-trade and fallen to half of that peak, no new entries that day; open positions keep their stops.
  - **Or don't.**
