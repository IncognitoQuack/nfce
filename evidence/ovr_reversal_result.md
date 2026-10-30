# OVR-1 (high-VIX, news-free overnight loser reversal): result. FAIL at train

**Protocol:** `ovr_reversal_protocol.md`, SHA-256 `23f54111ee8eb7278f5c32b9029cf42e999e335f5940cbc8ebedc0e3daa6b8f7`, registered 14:41 on 27 Oct 2026, before the run. **Code:** `nfce_engine/tools/ovr_reversal.py`. **Run:** 14:43, train stage only.

## Train 2022–24
| | Trades | Nights | Win % | Gross bp | **Net bp** (15 bp cost) | Day-block 95% | p | Worst night |
|---|---|---|---|---|---|---|---|---|
| **OVR-1 (VIX gate on)** | 365 | 147 | 53.7 | +0.6 | **−14.4** | −46.2 … +17.1 | 0.81 | −1,099 bp |
| Context: no VIX gate (not tested) | 1,529 | 649 | 54.3 | +14.6 | −0.4 | −13.7 … +13.1 | 0.60 | −1,099 bp |

**Verdict: FAIL.** The net is below zero and the interval includes zero. Validation and the final stage are not run.

## What it shows
- **The "+18 to +43 bp net" claimed in the Gemini report does not appear on NSE F&O stocks in 2022–24.** That claim was a US result with our costs subtracted, not an NSE measurement.
- **The VIX gate, the paper's key condition, made it worse here:** +0.6 bp gross with the gate, against +14.6 bp without it.
- **Without the gate:** a small gross overnight rebound exists (+14.6 bp), about equal to the cost, so net ≈ 0.
  - It is **context only**. Switching it on would be the hindsight error the method forbids.
  - It could be registered as a new hypothesis and tested on 2025 data it has not seen.
- **Tail risk:** the worst single position lost about 11% overnight.
