# Candidates from the ChatGPT and Gemini reports: result (20 Oct 2026)

> **Correction (review round 3, M10).** An earlier version of the evaluator prompt said these ideas were "implemented exactly". That overstated it. They are **adaptations** of the reports' ideas, fixed in `external_protocol.md` before any result:
> - spot index as a futures proxy;
> - fills at the next bar's open or at the level;
> - the option, premium-stop and gamma (NGE) parts left out;
> - S5c without its stop-and-reverse and ±1-point buffers.
>
> The honest conclusion is: **the tested adaptations showed no robust edge after costs**. The original option-based versions remain untested and are not disproved. The specific deviations are listed in `review_round3_response.md` (M10).

**Protocol:** `external_protocol.md` (SHA-256 `2d6d199b…`), frozen before any result. R5: `r5_protocol.md` (SHA-256 `a0d489a4…`).
**Code:** `nfce_engine/nfce/research2.py` (10 unit tests) and `tools/external_run.py`.
**Data:** Upstox 5m spot, 2022 – Jul 2026, with NIFTY and BANKNIFTY spot as a futures proxy.
**Costs:** the **current** (Oct 2026) futures costs on every trade.

## Claims checked against the sources
| Claim in the reports | Check |
|---|---|
| Medidala BANKNIFTY σ strategy: +183.8%, Sharpe 0.528, 3,624 trades, +145.9 pts per trade, 2015–2024 | **Matches the repository.** The repository also shows a *train* Sharpe of 0.004 (2015–19) versus 0.691 test (2020–24), with costs of only ₹75 per round trip plus 2 pts per side |
| Zarattini et al. 2024: +1,985%, 19.6% a year, Sharpe 1.33 (SPY) | **Matches the abstract** (US data) |
| STT 0.05% futures / 0.15% options from 1 Apr 2026; Tuesday expiries from Sep 2025; Bank Nifty weeklies ended Nov 2024 | **Correct**, and already in this system |

## TRAIN (2022–2024), current costs: net R per trade
| Rule | NIFTY | BANKNIFTY |
|---|---|---|
| S1 σ session-anchor momentum (ChatGPT #1) | −0.016 (902) | −0.010 (862), negative all 3 years |
| S2 / S2L noise-area momentum (Gemini #1) | −0.156 / −0.153 | −0.161 / −0.183 |
| S3 Williams prior-day range | −0.189 | −0.143 |
| **S4 Williams 3-day swing** | **+0.037 (218)** | −0.050 |
| S5 / S5c NR7, ID/NR4 | −0.246 / −0.210 | −0.137 / −0.141 |
| **S6 Oops gap reversal (VIX ≥ 15)** | −0.312 | **+0.103 (44)** |
| S7 weekend/holiday ORB | −0.208 | −0.133 |
| S8 morning ±0.5% (signal of ChatGPT #2) | −0.449 | −0.299 |
| S9 late momentum, no NGE (Gemini #4) | −0.144 | −0.274 |

**Two survivors:** S4 NIFTY and S6 BANKNIFTY.

## VALIDATION (2025)
| Survivor | Result | Verdict |
|---|---|---|
| S4 NIFTY | n 77, +0.059R (+8.7 pts), PF 1.23, p 0.26 | FAIL: not significant |
| S6 BANKNIFTY | n 6, +0.28R | FAIL: too few trades |

**Nothing passes.**

## R5: the separately registered one-shot test of S4 NIFTY on Jan–Jul 2026
- n 44, **+0.032R per trade but −13.7 points per trade**: the losing trades were the larger ones.
- PF 1.09 (bar 1.15) and day-block lower bound −0.25 (bar > 0).
- **FAIL.**

## Not testable with the available data
These need historical option prices or OI. Option bid/ask is now recorded live by the bridge (R1); OI history is not.
- the short straddle and 0DTE iron condor;
- OI unwinding;
- the option leg of the ±0.5% morning trade;
- NGE (dealer gamma) filtering;
- the 2:1 ratio spread, which is also **rejected for safety**: it leaves a net naked short option in the tail.

## Conclusion
- **No price-based idea from either report is profitable at 2026 costs on data it was not selected on.**
- **The strongest one (S4, NIFTY 3-day swing breakout) was positive in 3 of the 4 years at current costs,** but failed significance in 2025 and lost money in rupee terms in 2026.
- **The reports' top-ranked ideas fail after costs:** the BANKNIFTY σ momentum and the noise-area momentum. The σ strategy's gross edge (+0.02R) is smaller than today's costs (0.03R), consistent with its own repository's near-zero training Sharpe.

## Corrected re-run after review round 3 (20 Oct 2026)
The review found two real bugs in `research2.py`:
- **H09:** a target reached on the entry bar was ignored.
- **H10:** a position still open at the end of an incomplete day was dropped.

Both are fixed, with tests that fail on the old code. All 22 configurations were then run again, old code against new, trade by trade on the same 2022 – Jul 2026 data (`ledgers/external_S1_S9_trades.csv`):
- **0 trades added, 0 removed, 0 exits changed** in all 18 rule/index pairs that use these code paths.
- The reason: the targets are at least one R from the entry, so none was reached on its entry bar; and the Upstox history has no truncated sessions.
- **So every number above stands, and R5 is still FAIL** (n 44, +0.032R, −13.7 pts, PF 1.09).

**For transparency, Jan–Jul 2026 for all 22 configurations (exploratory, not a test).** Under the protocol, only validation survivors should ever have reached 2026, and none did. These numbers were computed after the selection was over, so they cannot select anything:

| Rule | NIFTY 2026 | BANKNIFTY 2026 |
|---|---|---|
| S1 | −0.017 (178) | −0.004 (180) |
| S2 / S2L | −0.057 / −0.319 | −0.045 / −0.183 |
| S3 | −0.709 | −0.029 |
| S4 | +0.032 (44), −13.7 pts | +0.227 (40) |
| S5 / S5c | +0.068 / +0.034 | +0.308 (23) / +0.333 (24, p 0.036) |
| S6 | −0.064 (7) | +0.444 (4) |
| S7 | −0.241 | −0.108 |
| S8 | −1.029 | −0.431 |
| S9 | −0.147 | −0.213 |

**What the BANKNIFTY positives mean:**
- **S4 and S5/S5c BANKNIFTY lost money in 2022–24 and in 2025** (S5 BANKNIFTY: −0.137 and −0.124).
- **One good half-year after four losing years** is what regime noise looks like.
- **The best p-value, 0.036, is not significant** once you correct for the 22 configurations (the bar would be 0.05 / 22 ≈ 0.0023).
- **None of them is registered as a lead.**
