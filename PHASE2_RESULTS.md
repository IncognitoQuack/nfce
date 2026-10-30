# NFCE — Phase 2: strategy backtest results (17 Oct 2026)

Files:
- `nfce_strategy.pine`: compiles on TradingView, Pine v6.
- `nfce_analysis.js`: the cost and statistics code used for the table below.

## Results (report defaults, 1 lot, net of 2026 costs)

| Instrument / TF | History tested | Trades | Win rate (net) | Avg R gross | **Avg R net** | t-stat (net R) | Profit factor (net) | Max DD (₹/lot) | Gross (₹/lot) | **Net after costs (₹/lot)** |
|---|---|---|---|---|---|---|---|---|---|---|
| NIFTY1! 5m | 13 Jul – 16 Oct 2026 (3 mo) | 19 | 42% | +0.01 | **−0.48** | −1.8 | 0.57 | 18,548 | +6,780 | **−11,965** |
| NIFTY1! 15m | 1 Dec 2025 – 16 Oct 2026 (10.5 mo) | 38 | 42% | +0.11 | **−0.13** | −0.8 | 0.66 | 55,561 | +6,779 | **−31,236** |
| BANKNIFTY1! 5m | 13 Jul – 16 Oct 2026 (3 mo) | 10 | 30% | −0.15 | **−0.61** | −2.0 | 0.25 | 16,395 | −5,301 | **−15,983** |
| BANKNIFTY1! 15m | 1 Dec 2025 – 16 Oct 2026 (10.5 mo) | 31 | 55% | +0.24 | **+0.04** | +0.2 | 1.10 | 23,594 | +40,609 | **+7,240** |

TradingView's own Strategy Tester confirms these numbers. Its 10-lot run, divided by 10, gives:

| | Net per lot | Max DD per lot |
|---|---|---|
| NIFTY 5m | −11,844 | 18,932 |
| NIFTY 15m | −31,073 | 57,566 |
| BANKNIFTY 5m | −15,933 | 17,771 |
| BANKNIFTY 15m | +7,391 | 26,533 |

My trade ledger and TradingView's broker emulator agree to within about 1–2%.

**Plain reading:**
- Before costs the system is roughly break-even (+0.01R to +0.24R per trade).
- Costs are about **0.06% of notional per round trip plus slippage, which is 0.20–0.49R per trade**. They turn three of the four tests negative.
- The only positive result (Bank Nifty 15m, +0.04R) is statistically indistinguishable from zero (t = 0.2, 31 trades).
- None of the four tests has the 200+ trades the report itself requires before trusting a win rate.

## How the backtest works
- **Entries:** at the signal bar's close, the same price as the indicator's "Entry".
- **Exits:**
  - 40% at T1 (1R), then SL moves to breakeven.
  - 30% at T2 (2R), then SL moves to T1.
  - The rest goes at T3 (3R), the trailing stop, or the close of the bar ending at 15:15.
  - If the SL and a target are both inside one bar, the SL counts first (conservative).
  - A stop that gaps is filled at the bar's open.
- **Costs per trade (per lot):**
  - 0.03% of notional per side, covering STT 0.05% sell, exchange charges, stamp duty, ₹20×2 brokerage and GST. That's ≈ ₹965 round trip on Nifty, as in report §3.
  - Plus 4 ticks of slippage per side.
  - The 15m tests start Dec 2025, before the 1 Apr 2026 STT increase, so Dec–Mar trades are costed at the higher 2026 rate. That's slightly conservative for those months.
- **Instrument settings:**
  - NIFTY uses the report's default heavyweights.
  - BANKNIFTY uses Instrument = BANKNIFTY (monthly expiry only) with HDFCBANK, ICICIBANK, SBIN, KOTAKBANK and AXISBANK as heavyweights, per report §2.

## Strategy vs indicator: parity
- Sections 1–9 of the strategy are **byte-identical** to the indicator's (checked by diff).
- Section 10 runs the indicator's state machine unchanged, and TradingView orders follow it.
- Two in-script counters measure disagreement between TradingView's broker emulator and the state machine:
  - `mmStateFlat`: emulator still in a trade the state machine closed.
  - `mmEmuFlat`: emulator flat while the state machine is in a trade.
  - Both were **0 on all four runs**.
- Remaining, intended differences:
  1. The emulator fills stop orders with slippage and may fill a gapped stop at the open. The indicator's label always shows the planned SL.
  2. The indicator books "40% / 30% / rest" only on its labels. The strategy needs whole contracts, so it trades **10 lots (4/3/3)**; all ₹ figures above are per lot.

## Report errors found and fixed (strategy header in §3)
1. **`default_qty = 65` does not exist.** It's a compile error; the argument is `default_qty_value`.
2. **Quantity 65 meant 65 lots, not one lot.** On TradingView NSE index futures one contract is already one lot (`syminfo.pointvalue` = 65 for NIFTY1!, 30 for BANKNIFTY1!).
3. **No margin was set.** Pine v6 defaults to 100% margin. Combined with ₹5 lakh capital, every order was rejected and the backtest showed **zero trades**.
   - Fixed with `margin_long/short = 15` (approx. SPAN + exposure), 10 lots and ₹30 lakh capital.
4. **`process_orders_on_close = false`** (report) fills at the next bar's open, so it wouldn't match the indicator's entry price. Set to `true`; the difference is covered by slippage.
5. **Delayed-data prefix.** On your delayed feed `syminfo.prefix` is `NSE_DLY`. The webhook JSON now normalises it to `NSE`. This fix also went into `nfce_indicator.pine`.

## Limits of this test
- **History is short.**
  - TradingView loaded ~5,200 bars per chart on your plan: 3 months on 5m, 10.5 months on 15m.
  - That gives 10–38 trades per test.
  - Each win rate above has a ±15–30 percentage-point sampling error.
- **No walk-forward is possible** on 3 months of 5m data.
- Results are on continuous futures (`1!`). Real fills at rollover and on illiquid minutes can be worse.
