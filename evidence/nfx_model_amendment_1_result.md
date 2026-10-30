# NFCE-X M1-A1 (executable entry): train-stage result. Not taken forward

**Amendment:** `nfx_model_amendment_1.md`, SHA-256 `58db352c996156d9c87452d002822c9784a36fb8675e1d11e4f692392e83a66b`, registered 15:36 on 27 Oct 2026, before the run. **Code:** `tools/nfx_model.py --stage train --target x1` (store labels `y_x1`, `y_x2`, `y_x5` from `nfx/features.py: exec_labels`). Output: `nfx_features/_m1a1_train.json`.

| Test (unseen by its model) | M1-A1 net bp (entry at the next bar's open) | 95% CI | p | Entry at +2 bars | Entry at +5 bars | Ridge B1 | IC |
|---|---|---|---|---|---|---|---|
| 2023 H1 | **−13.9** (gross +1.1, 268 trades) | −38.8 … +7.8 | 0.93 | −15.8 | −18.4 | −8.6 | 0.030 |
| 2023 H2 | **−6.1** (gross +8.9, 163) | −39.0 … +24.6 | 0.56 | −7.0 | −26.1 | −4.9 | 0.039 |
| 2024 | **+21.1** (gross +36.1, 387) | −15.1 … +59.8 | 0.011 | +12.2 | +3.6 | +1.7 | 0.027 |

## Verdict
- **Negative in 2 of 3 folds, as predicted in the amendment.** The 2024 fold is positive on the day t-test, but its bootstrap interval spans zero. That is fat-tailed: a few big days.
- **Not "clearly positive", so the 2025 validation look is NOT spent** (the amendment's rule). Validation and the final stay unused.
- **The IC is real but small** (0.027–0.039 with an executable entry). It is too little to clear 15 bp a round trip in stock futures.
- **What would change that:** cheaper execution (passive fills: GS measures this live), or new information that history lacks (options, the live order book, news timing: Phase 1b, recorded forward from 26 Oct).
