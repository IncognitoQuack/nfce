# Reversed stock signals: result. FAIL, as predicted

**Protocol:** `reversed_signals_protocol.md`, SHA-256 `5e28c28db685c5a55e19543e95d83f3949006bea91d74d367793e5a3551fbd68`, registered 14:39 on 27 Oct 2026, before the run. **Code:** `nfce_engine/tools/reversed_signals.py`. One engine run, train 2022–24, 210 F&O stocks.

| | Trades | Win % | Gross R | **Net R** | Day-block 95% | PF | ₹ (1 lot each) |
|---|---|---|---|---|---|---|---|
| V0, the signals as given | 16,598 | 51.5 | +0.051 | **−0.270** | −0.290 … −0.249 | 0.66 | −93.9 L |
| **REV, the opposite side** | 16,598 | 46.4 | −0.054 | **−0.374** | −0.391 … −0.357 | 0.53 | −147.2 L |

- **V0 reproduces** the registered stock 3m result exactly (16,598 trades, +0.051 gross, −0.270 net), so the run is the same one.
- **REV is worse,** as predicted in the protocol (about −0.37R). The signals are not reversed: they carry a small edge in the right direction (+0.05R), and costs (~0.32R) are what make both sides lose.
- **Answer to the admin's question (27 Oct 12:03):** no. Taking the opposite side loses more, about ₹53 L more over 2022–24 at one lot per signal.
