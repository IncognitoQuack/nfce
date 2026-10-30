# Study engine: result (26 Oct 2026)

**Protocol:** `study_engine_protocol.md`, SHA-256 `038e4dfe21c492df9bbe2f3b3f494db857bfdc3f9a9fa2a632e486e35f704862`, registered at 10:36 IST, before any run (REGISTRY row added then).
**Code:** `nfce_engine/tools/study.py`, with 36 tests in `nfce_engine/tests/test_study.py`:
- no look-ahead, for every indicator;
- walk parity with `research2._walk`;
- cost parity with `costs.futures_cost_points`;
- Holm, SPA and DSR checks;
- a cost-check on a synthetic database.

**Every rule's numbers:** `study_engine_rules.csv` (2,232 rows). The tables below are printed by `python tools/study.py report`.
**Runs:**
- train 10:37 (18 s, 6 workers, `nice -n 15`);
- validation about 10:38, right after train (3 s);
- the final was **not run** (nothing to run).

## Bottom line
- **2,232 rules tried; 0 survive.** Not one indicator rule is profitable after costs in a way that holds up.
  - 23 rules went from train to validation (the best setting per family, and only where train was positive).
  - All 23 failed validation.
  - So, by the protocol, the one-shot final on 2025–26 was not run.
- **Before costs, these indicators have no edge at all.**
  - The median rule's gross result is −0.005R per trade, and 44% of rules are gross-positive: a coin flip.
  - After costs the median is −0.091R; only 36 of the 2,040 rules with ≥ 100 trades were above zero on 2022–23.
- **Data-mining check on train: the best of all 2,232 rules is no better than luck.**
  - White's reality check p = 0.57; Hansen's SPA p = 0.12.
  - On validation, the 23 candidates: reality check p = 0.30, SPA p = 0.60.
- **The cost model is too kind, so the true picture is worse** (cost check below).
  - Live stock-futures spreads are about 2.3× the model's friction.
  - NIFTY futures spreads are about 6× the model's friction.
- **The only family that stayed positive on both train and 2024 is "fade a big gap"** (≥ 2% open gap; trade against it after the first 3-minute bar, 2× exits). But:
  - it is +0.02 to +0.15R per trade on a few hundred to 2,000 trades;
  - no 2024 p-value is below 0.04;
  - every Holm-adjusted p is 1.000.
  - It is a **weak lead, not a result**. The earlier gap study (`gap_result.md`) already found that following the NIFTY gap loses.
- **Nothing is switched on, and no live protocol is proposed** (the protocol allows a proposal only for survivors).

## Scale
- **Rules:** 2,232.
  - 1,224 on 213 F&O stocks (pooled, 3-minute bars).
  - 1,008 on NIFTY and BANKNIFTY futures (pooled, 5-minute bars).
  - Built from 16 indicators and 37 settings × long/short × exits K1/K2/K4 × all-day/morning × VIX regime ALL/HI/LO.
- **Train (2022–23):** 41.7 million rule-trades (one trade per rule, instrument and day at most). 2,040 rules have ≥ 100 trades.

**Median train net R per trade, by exit** (as in `wide_stop_result.md`, wider exits shrink the cost share and the loss, never into profit):

| Exit | Median net R (2022–23) |
|---|---|
| K1 | −0.188 |
| K2 | −0.092 |
| K4 | −0.045 |

**By indicator** (rules with ≥ 100 train trades; net after costs):

| Indicator | Best rule, net R | Median rule, net R | Median gross R |
|---|---|---|---|
| GAP_FADE | +0.078 | −0.038 | +0.038 |
| BB_FADE | +0.060 | −0.085 | −0.000 |
| GAP_CONT | +0.032 | −0.100 | −0.041 |
| NR_ORB | +0.021 | −0.049 | +0.016 |
| BB_BRK | +0.016 | −0.103 | −0.007 |
| ADX_DI | +0.009 | −0.097 | −0.004 |
| VWAP_MR | +0.006 | −0.068 | −0.007 |
| RSI_TR | +0.005 | −0.104 | −0.008 |
| VWAP_X | −0.007 | −0.069 | +0.002 |
| EMA_X | −0.008 | −0.098 | −0.007 |
| RSI_MR | −0.011 | −0.097 | −0.008 |
| PDHL | −0.012 | −0.111 | −0.012 |
| ST (Supertrend) | −0.012 | −0.100 | −0.005 |
| MACD | −0.015 | −0.097 | −0.013 |
| ORB | −0.015 | −0.085 | +0.007 |
| RVOL | −0.022 | −0.070 | +0.006 |

## Multiple-testing verdict
| Test | Stage, rules | p | Reading |
|---|---|---|---|
| White's reality check | train, 2,226 rules with trades | 0.574 | the best train rule is what luck alone would produce |
| Hansen's SPA (consistent) | train, 2,226 | 0.122 | not significant |
| White's reality check | validation, 23 candidates | 0.297 | not significant |
| Hansen's SPA | validation, 23 | 0.604 | not significant |
| Holm (family = all 2,232 rules) | validation | adjusted p = 1.000 for all 23 | none near 0.05 |
| Deflated Sharpe (N = 2,232) | validation | 0.000 for all 23 | see the note below |
| PBO, CSCV (added 26 Oct, 11:45; Bailey et al., SSRN 2326253) | train, the 2,040 rules with ≥ 100 trades; 16 blocks, 12,870 splits | **PBO = 0.00** | the in-sample best has a per-day Sharpe of +0.192 in sample and +0.085 out of sample (negative in 6% of splits); see the note below |

**About the PBO:**
- PBO asks whether the rule picked in-sample still ranks above the **median of the other rules** out of sample.
- Most rules here lose steadily after costs, so a rule that is merely around zero (the gap-fade family) keeps ranking high. So PBO = 0 means that **the ranking within 2022–23 is stable**, not that any rule beats zero.
- The tests against zero are the reality check, the SPA, Holm and the forward stages, and all of them fail.
- The forward record of that family: 2024 validation not significant; the one-shot 2025–26 final in `study2_result.md` (H7) also FAILED.

**About the DSR:**
- The expected best per-day Sharpe of 2,232 skill-less rules is 0.595, computed from the spread of the train Sharpes, V = 0.0293.
- That spread is wide because many rules lose steadily, so this bar is very high.
- The verdict does not depend on it: without any correction, only one candidate had a 2024 p(day) below 0.05 (0.040, at +0.025R).

## Top 25 rules on train (2022–23), after costs (rules with ≥ 100 trades)
| Rule | n | Win % | Gross R | Net R | 2022 | 2023 | p(day) | Cost/R | Candidate | 2024 (val) |
|---|---|---|---|---|---|---|---|---|---|---|
| `GAP_FADE\|L\|K2\|ALL\|VIXLO\|STK\|0.02` | 733 | 53.1 | +0.140 | **+0.078** | +0.106 | +0.016 | 0.1779 | 0.06 | yes | +0.148 |
| `BB_FADE\|L\|K2\|AM\|VIXHI\|IDX\|20,2.5` | 120 | 55.0 | +0.164 | **+0.060** | +0.105 | +0.011 | 0.2259 | 0.10 | yes | −0.132 |
| `GAP_FADE\|S\|K4\|ALL\|VIXHI\|STK\|0.02` | 1,277 | 54.3 | +0.079 | **+0.051** | +0.062 | +0.029 | 0.0011 | 0.03 | yes | +0.016 |
| `GAP_FADE\|S\|K2\|ALL\|VIXHI\|STK\|0.02` | 1,277 | 54.1 | +0.101 | **+0.045** | +0.059 | +0.019 | 0.0083 | 0.06 | yes | +0.028 |
| `GAP_FADE\|S\|K2\|ALL\|ALL\|STK\|0.02` | 2,030 | 53.7 | +0.100 | **+0.042** | +0.053 | +0.025 | 0.0050 | 0.06 | yes | +0.030 |
| `GAP_FADE\|S\|K4\|ALL\|ALL\|STK\|0.02` | 2,030 | 53.9 | +0.066 | **+0.037** | +0.043 | +0.026 | 0.0009 | 0.03 | yes | +0.025 |
| `GAP_CONT\|S\|K4\|ALL\|VIXHI\|STK\|0.02` | 1,080 | 50.7 | +0.060 | **+0.032** | +0.100 | −0.185 | 0.9534 | 0.03 | yes | +0.048 |
| `GAP_FADE\|L\|K2\|ALL\|VIXLO\|STK\|0.01` | 2,364 | 51.3 | +0.097 | **+0.029** | +0.026 | +0.036 | 0.8575 | 0.07 |  | – |
| `GAP_FADE\|S\|K4\|ALL\|VIXHI\|STK\|0.01` | 5,622 | 53.3 | +0.058 | **+0.028** | +0.045 | −0.005 | 0.0017 | 0.03 |  | – |
| `GAP_FADE\|S\|K2\|ALL\|VIXLO\|STK\|0.02` | 702 | 52.4 | +0.087 | **+0.026** | +0.019 | +0.033 | 0.1564 | 0.06 | yes | +0.032 |
| `GAP_FADE\|L\|K1\|ALL\|VIXLO\|STK\|0.02` | 733 | 55.5 | +0.144 | **+0.022** | +0.082 | −0.116 | 0.2383 | 0.12 | yes | +0.118 |
| `NR_ORB\|L\|K4\|ALL\|ALL\|IDX\|nr7` | 103 | 54.4 | +0.076 | **+0.021** | +0.090 | −0.052 | 0.3596 | 0.05 | yes | −0.067 |
| `BB_FADE\|L\|K2\|AM\|VIXHI\|IDX\|20,2.0` | 192 | 52.1 | +0.125 | **+0.021** | +0.017 | +0.025 | 0.2626 | 0.10 |  | – |
| `GAP_FADE\|L\|K4\|ALL\|VIXLO\|STK\|0.02` | 733 | 48.6 | +0.051 | **+0.020** | +0.032 | −0.007 | 0.6281 | 0.03 | yes | +0.095 |
| `GAP_FADE\|S\|K2\|ALL\|VIXHI\|STK\|0.01` | 5,622 | 53.2 | +0.081 | **+0.019** | +0.039 | −0.017 | 0.0004 | 0.06 |  | – |
| `GAP_FADE\|L\|K2\|ALL\|ALL\|IDX\|0.005` | 125 | 48.8 | +0.105 | **+0.018** | +0.057 | −0.149 | 0.7145 | 0.09 | yes | −0.109 |
| `BB_BRK\|L\|K4\|ALL\|VIXLO\|IDX\|20,2.5` | 274 | 55.5 | +0.072 | **+0.016** | +0.013 | +0.020 | 0.4444 | 0.06 | yes | −0.053 |
| `GAP_CONT\|S\|K4\|ALL\|VIXHI\|STK\|0.01` | 3,137 | 50.9 | +0.046 | **+0.016** | +0.058 | −0.128 | 0.8453 | 0.03 |  | – |
| `BB_FADE\|L\|K4\|AM\|VIXHI\|IDX\|20,2.0` | 192 | 48.4 | +0.068 | **+0.016** | +0.002 | +0.030 | 0.2341 | 0.05 | yes | −0.100 |
| `GAP_FADE\|S\|K4\|ALL\|VIXHI\|STK\|0.005` | 14,767 | 53.4 | +0.050 | **+0.016** | +0.041 | −0.012 | 0.1681 | 0.03 |  | – |
| `GAP_FADE\|L\|K2\|ALL\|VIXLO\|STK\|0.005` | 5,188 | 51.3 | +0.087 | **+0.016** | +0.011 | +0.025 | 0.9674 | 0.07 |  | – |
| `GAP_FADE\|S\|K2\|ALL\|VIXHI\|STK\|0.005` | 14,767 | 53.3 | +0.082 | **+0.013** | +0.046 | −0.024 | 0.0314 | 0.07 |  | – |
| `ADX_DI\|S\|K2\|AM\|VIXHI\|IDX\|20` | 160 | 51.9 | +0.117 | **+0.009** | +0.019 | −0.001 | 0.7067 | 0.11 | yes | −0.037 |
| `GAP_FADE\|L\|K4\|ALL\|VIXLO\|STK\|0.01` | 2,364 | 48.4 | +0.042 | **+0.008** | +0.006 | +0.015 | 0.7790 | 0.03 |  | – |
| `GAP_FADE\|S\|K4\|ALL\|VIXLO\|STK\|0.02` | 702 | 52.4 | +0.037 | **+0.006** | −0.007 | +0.022 | 0.1247 | 0.03 | yes | +0.042 |

**How to read a rule id:** indicator | side | exit | window | VIX regime | universe | setting.
- `GAP_FADE|L|K2|ALL|VIXLO|STK|0.02` means: buy a stock that opened ≥ 2% below the prior close, after the first 3-minute bar, with a 2R stop and target, on low-VIX days.
- Rows without "Candidate" were beaten by another setting of the same family on train, so they were not validated.

## Validation 2024: the 23 candidates (all FAIL)
| Rule | Train net R | n | Win % | Net R 2024 | p(day) | Holm (all rules) | DSR | Pass |
|---|---|---|---|---|---|---|---|---|
| `GAP_FADE\|L\|K2\|ALL\|VIXLO\|STK\|0.02` | +0.078 | 429 | 58.0 | **+0.148** | 0.1984 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|L\|K1\|ALL\|VIXLO\|STK\|0.02` | +0.022 | 429 | 61.1 | **+0.118** | 0.6151 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|L\|K4\|ALL\|VIXLO\|STK\|0.02` | +0.020 | 429 | 54.8 | **+0.095** | 0.2204 | 1.000 | 0.000 | FAIL |
| `GAP_CONT\|S\|K2\|ALL\|VIXHI\|STK\|0.02` | +0.004 | 423 | 54.8 | **+0.062** | 0.8566 | 1.000 | 0.000 | FAIL |
| `GAP_CONT\|S\|K4\|ALL\|VIXHI\|STK\|0.02` | +0.032 | 423 | 52.5 | **+0.048** | 0.5577 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|S\|K4\|ALL\|VIXLO\|STK\|0.02` | +0.006 | 500 | 55.0 | **+0.042** | 0.1037 | 1.000 | 0.000 | FAIL |
| `NR_ORB\|S\|K2\|AM\|VIXHI\|STK\|inside` | +0.005 | 1,681 | 53.2 | **+0.037** | 0.8241 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|S\|K2\|ALL\|VIXLO\|STK\|0.02` | +0.026 | 500 | 53.8 | **+0.032** | 0.1732 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|S\|K2\|ALL\|ALL\|STK\|0.02` | +0.042 | 1,374 | 53.0 | **+0.030** | 0.2408 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|S\|K2\|ALL\|VIXHI\|STK\|0.02` | +0.045 | 874 | 52.5 | **+0.028** | 0.5019 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|S\|K4\|ALL\|ALL\|STK\|0.02` | +0.037 | 1,374 | 52.5 | **+0.025** | 0.0404 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|S\|K4\|ALL\|VIXHI\|STK\|0.02` | +0.051 | 874 | 51.1 | **+0.016** | 0.1152 | 1.000 | 0.000 | FAIL |
| `NR_ORB\|S\|K4\|AM\|VIXHI\|STK\|nr7` | +0.005 | 1,605 | 52.0 | **−0.001** | 0.8544 | 1.000 | 0.000 | FAIL |
| `NR_ORB\|S\|K4\|ALL\|VIXHI\|STK\|inside` | +0.001 | 2,046 | 50.3 | **−0.003** | 0.9521 | 1.000 | 0.000 | FAIL |
| `VWAP_MR\|L\|K4\|AM\|VIXHI\|STK\|0.015` | +0.006 | 2,360 | 50.0 | **−0.007** | 0.1517 | 1.000 | 0.000 | FAIL |
| `ADX_DI\|S\|K2\|AM\|VIXHI\|IDX\|20` | +0.009 | 94 | 51.1 | **−0.037** | 0.6731 | 1.000 | 0.000 | FAIL |
| `BB_BRK\|L\|K4\|ALL\|VIXLO\|IDX\|20,2.5` | +0.016 | 179 | 38.5 | **−0.053** | 0.9863 | 1.000 | 0.000 | FAIL |
| `RSI_TR\|L\|K4\|ALL\|VIXLO\|IDX\|14,70` | +0.005 | 137 | 35.8 | **−0.064** | 0.9609 | 1.000 | 0.000 | FAIL |
| `BB_FADE\|L\|K2\|AM\|ALL\|IDX\|20,2.5` | +0.001 | 175 | 50.9 | **−0.066** | 0.7296 | 1.000 | 0.000 | FAIL |
| `NR_ORB\|L\|K4\|ALL\|ALL\|IDX\|nr7` | +0.021 | 52 | 28.8 | **−0.067** | 0.9474 | 1.000 | 0.000 | FAIL |
| `BB_FADE\|L\|K4\|AM\|VIXHI\|IDX\|20,2.0` | +0.016 | 118 | 44.1 | **−0.100** | 0.8094 | 1.000 | 0.000 | FAIL |
| `GAP_FADE\|L\|K2\|ALL\|ALL\|IDX\|0.005` | +0.018 | 38 | 50.0 | **−0.109** | 0.7472 | 1.000 | 0.000 | FAIL |
| `BB_FADE\|L\|K2\|AM\|VIXHI\|IDX\|20,2.5` | +0.060 | 86 | 45.3 | **−0.132** | 0.8490 | 1.000 | 0.000 | FAIL |

**What the table shows:**
- **12 of 23 candidates stayed positive in 2024.** All 12 are stock rules, and 11 of them are gap rules.
- **Every index candidate turned negative.**
- **"Positive" is not "proven".** A positive mean on a few hundred trades with p(day) 0.1–0.9 is what noise looks like.

## Final 2025-01 .. 2026-10-21
**Not run.** No rule passed validation. The one-shot sample stays unused, so a future, newly registered test can still use it once.

## Cost-model check (live minute quotes; used for nothing else)
**Data:** 127,521 futures quotes from `study_quotes_20261022.db` (11:45 onward) and `study_quotes_20261023.db` (the full day), covering 214 stock futures and NIFTY. The 26 Oct file is still being recorded and was not read. The `study_1m` candles have no bid/ask, so they cannot measure spread and were not used.

| Item | Measured (live) | Model | Verdict |
|---|---|---|---|
| Stock futures quoted half-spread, median of the per-stock medians | **4.6 bp** (75%: 5.6 bp, 90%: 6.8 bp) | 2.0 bp per side (half-spread + slippage) | model **too low**; 97% of stocks exceed it on the spread alone |
| … first 15 minutes | 6.2 bp | 2.0 bp | wider still at the open, which hurts the gap rules most |
| ~₹7 L stock lot inside the touch, both sides | 41% of quotes | assumed always | more than half the time the lot would walk the book |
| NIFTY futures half-spread | **2.55 pts** median (90%: 4.7) | 0.4 pts (4 ticks) per side | model **far too low** (minute snapshots; possibly some stale quotes) |

**What that does to the numbers:**
- The median stock ATR is about 3.0%, so R ≈ 0.76% of price.
- The measured spread alone adds about 2 × (4.6 − 2.0) bp = 5.2 bp per round trip.
- In R, that is +0.069R per trade at K1, +0.034R at K2 and +0.017R at K4.
- **Every stock result in this study, and in the earlier stock studies that use the same 0.02% friction, is therefore optimistic by about that much.** That is about a quarter of the best 2024 rule's margin (+0.148R at K2), and all of the margin of the short-side gap rules (+0.016 to +0.042R). The open, where the gap rules trade, has the widest spreads.
- **The index results are optimistic by more.**
- **This makes the conclusion stronger, not weaker.**
- The friction setting is shared with the frozen research tools, so it is **not** changed here. A recommendation is in "Next".

## Limits
- One trade per rule, instrument and day (the first signal in the window). Rules that re-enter many times a day are not modelled.
- Futures execution only. Option execution, the one lever that earlier studies said could change the cost side, still has no history to test.
- The current 2026 fee schedule is charged for every year, as in the earlier studies.
- 2022–24 was seen by earlier tests of the NFCE signals. These indicator rules had not been run on it before.

## News and LLMs (the owner's question today)
**This cannot go into a historical test honestly:**
- There is no archive of the news as it was known at each bar.
- An LLM reading old headlines already knows how those days ended (its training data), so a backtest would leak the outcome.

**The only dated "news" in the data, NSE results days, was tested on 23 Oct:** signals did not do worse; the result is a flag only (`results_days_result.md`).

**A news + LLM filter can only be measured forward.** That would need:
- its own locked protocol;
- the LLM's verdict logged before the trade;
- judging after a fixed number of sessions, like the strategy accounts.

## Next (proposals only; nothing is switched on)
1. **Raise the model's stock friction** to the measured level for future studies, after more quote days (at least 5 full sessions).
   - Re-check the index spread, since the minute snapshots may include stale quotes.
2. **The gap-fade lead** (≥ 2% gap, fade after the first bar).
   - It is positive in 2022, 2023 and 2024 on the long side in low VIX, but nowhere near significant.
   - With realistic spreads it is close to zero.
   - A fresh test would need a new registration and the untouched 2025–26 sample used once. The owner's call; it is **not** recommended as a priority.
