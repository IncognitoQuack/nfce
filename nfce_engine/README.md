# NFCE engine v2 (Python port and research tools)

This is a bar-by-bar Python port of `nfce_strategy.pine` v2. It uses the same inputs, presets, factors, filters, state machine and v2 trade rules:
- close-time cut-offs;
- no same-bar re-entry;
- the moved stop enforced in the same bar;
- the daily stop.

`LEGACY_V1` reproduces the Phase 2–3 behaviour.

**107 tests**, all passing (`python -m pytest -q`).

## What is here
| File | Purpose |
|---|---|
| `nfce/ta.py` | TradingView-exact indicator maths (EMA/RMA seeding, ATR, DMI/ADX, Supertrend with NaN warm-up, linreg, population stdev) |
| `nfce/engine.py` | `prepare` (validates context timeframes, config fingerprint) and `run` (state machine, optional per-bar trace and mark-to-market curve) |
| `nfce/costs.py` | Dated Indian F&O fee schedule; byte-identical to `nfce_bridge/bridge/costs.py` |
| `nfce/stats.py` | `report`: dated or current costs, t-test, day/week block bootstrap, Clopper-Pearson, Holm, PF, drawdown |
| `nfce/data.py` | CSV validation (empty, NaN, duplicates, OHLC, grid, session) and the SHA-256 `MANIFEST.json` |
| `nfce/simple.py` | Pre-registered simple hypotheses: H1 ORB, H2 momentum, H-A (R2) |
| `nfce/options_exec.py` | Option execution from real quotes (R1) |
| `nfce/robust.py` | Bounded tick-rounded perturbations; precision/recall/Jaccard |
| `nfce/registry.py` | Frozen pass/fail rules of R1–R3 |
| `tools/fetch_yahoo.py` | Download and validate Yahoo data, update the manifest (`--interval 5m/15m/60m/1d`) |
| `tools/robustness.py` | Baseline, noise and parameter study on 5m data (`NSEI` / `NSEBANK`) |
| `tools/simple_ideas.py` | H1/H2 on 60m data, dated / current / legacy costs, Holm |
| `tools/paper_replay.py` | Bridge paper ledger vs engine on real bars |
| `tools/tv_evidence.py` | Re-analyse the TradingView v2 trades in `../evidence/` |
| `tools/registry_eval.py` | Score R1/R2/R3 |
| `tools/sim3d.py`, `tools/sim250.py` | Paper simulations on the last N / random sessions (protocols in `../evidence/`) |
| `tools/build_evidence.py` | Builds the bridge's evidence table from hold-out trades |
| `nfce/research.py`, `tools/research_run.py` | Multi-year research: ORB, momentum, VWAP trend, historical expiry calendar (`../evidence/research_*.md`) |
| `tools/ml_study.py` | Direction / range / target-before-stop models on 4.5 years of 5m data (`../evidence/ml_*.md`) |
| `tools/train_range_model.py`, `nfce/registry_r4.py`, `tools/registry_eval_r4.py` | R4: train the live range model; frozen pass/fail rule and scoring (`../evidence/r4_protocol.md`) |
| `nfce/research2.py`, `tools/external_run.py` | S1–S9: candidates from the ChatGPT and Gemini reports, staged train / validation / one-shot at current costs (`../evidence/external_*.md`, `r5_protocol.md`) |
| `tools/range_benchmark.py`, `tools/registry_eval_r6.py` | Range-forecast benchmark against baselines on fresh data (`../evidence/range_benchmark_*.md`); scorer of the live R6 benchmark |
| `tools/golden_parity.py` | Bar-by-bar engine vs TradingView, from the strategy's golden export (Pine Logs CSV) |
| `run_backtest.py` | Backtest any CSV of bars (`--instr`, `--ablate`, `--legacy`) |

## Reproduce Phase 7
```bash
pip install numpy pandas scipy pytest yfinance
python -m pytest -q
python tools/fetch_yahoo.py && python tools/fetch_yahoo.py --interval 60m
python tools/robustness.py NSEI --seeds 20
python tools/robustness.py NSEBANK --seeds 20
python tools/simple_ideas.py
python tools/paper_replay.py NSEI
python tools/tv_evidence.py
```
Yahoo serves only recent data, so a fresh download covers a later window than Phase 7. The manifest hashes show which data produced which numbers.

## Data limits
- **Spot indices have no volume or OI.** The Yahoo runs use the summed volume of five heavyweights as a proxy, so they test a close relative of the TradingView system, not the same one.
- **Multi-year futures data needs a paid source**, e.g. TradingView Premium Deep Backtesting or a data vendor. Spending money on data is your decision.
- **Parity with TradingView:** proven bar by bar with `tools/golden_parity.py` on the strategy's golden export (`../PHASE7_V2_EVIDENCE.md` §D2). Pass `daily=` (daily bars) to `prepare` so previous-day levels use the settlement close, as Pine does.
