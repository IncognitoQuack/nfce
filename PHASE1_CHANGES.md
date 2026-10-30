# NFCE — Phase 1: indicator compile + repaint audit (17 Oct 2026)

File: `nfce_indicator.pine` (Pine v6, 455 lines). Changes in the code are marked `// FIX:`.

## Result
- **Compiles cleanly on TradingView** (Pine Editor console: "Compiled. Added to chart.", no errors or warnings), on NSE:NIFTY1! 5m.
- The report's code had **no compile errors as written**. The changes below fix logic/repaint/JSON bugs, not syntax.

## Changes and why
| # | Change | Why |
|---|---|---|
| 1 | Webhook JSON built by string concatenation instead of `str.format('{{"symbol":"{0}"...}}')` | **Bug in report.** `{{` is not an escape in Pine's MessageFormat-style `str.format`, and numeric `{n}` arguments are formatted with thousands separators (`24,512.5`) → invalid JSON for the Phase-4 bridge. |
| 2 | JSON `symbol` uses `syminfo.prefix:ticker` (e.g. `NSE:NIFTY1!`), and a `"tf"` field was added | `syminfo.tickerid` can carry modifier syntax with quotes that breaks JSON. `tf` lets the bridge tell 5m signals from 15m ones. |
| 3 | Square-off uses the bar **close** time (`time_close`) | **Bug in report.** It compared the bar *open* time with 15:15. On 15m charts, the 15:15 bar closes at 15:30, so trades were squared off at the close of market instead of 15:15. They now exit on the bar that closes at or after 15:15 (15:10 bar on 5m, 15:00 bar on 15m). A position open at a new day is also force-closed (safety only; never triggered). |
| 4 | Drawings never change retroactively. Lines extend while the trade is open and freeze at exit, and an SL move (BE / trail-to-T1) starts a new dotted SL segment. Old trades' lines are no longer deleted. | Repaint rule "nothing changes after bar close". The report moved the SL line's y-values on past bars (`set_y1/set_y2`) and deleted the previous trade's lines at every new signal. |
| 5 | RVOL ring buffer has `rvolDays + 1` rows | The report's buffer averaged only `rvolDays − 1` prior sessions (9, not 10). |
| 6 | Removed unused `f_lines` | As noted in the report; dead code referencing line history. |
| 7 | **New inputs, all defaulting to report behaviour:** `RVOL threshold override`, `Breakout length override` (0 = preset), `Require volume surge as hard filter` (off) | Needed for the Phase-3 optimisation (3 parameters) and for ablation. See finding A. |

## Repaint audit
- `request.security` calls (11 of 40):
  - **HTF** (`htfTF`): `[close[1], ta.ema(close,20)[1]]` with `lookahead_on`. Correct non-repainting pattern.
  - **Daily PDH/PDL/PDC**: `[high[1], low[1], close[1]]` with `lookahead_on`. Correct.
  - **VIX daily** (`close[1]`, `lookahead_on`). Correct.
  - **Same-timeframe** requests (futures vol/close, `_OI`, VIX intraday, 5 heavyweights): default `lookahead_off`. These don't repaint on history.
    - Residual caveat: in real time, another symbol's last tick can arrive slightly after the chart bar's last tick. That's a tiny difference, inherent to any multi-symbol script.
- All entries, exits, labels, lines and `alert()` calls sit inside `if barstate.isconfirmed`.
  - The dashboard is the only thing that reads the live bar, and it is labelled as such.
- State machine: no new trade while one is open. The SL is checked before targets within a bar (conservative). T1 → SL to breakeven, T2 → SL to T1, T3 or 15:15 → flat.

## Chart sanity check (NSE:NIFTY1!, 5m, 21 Jul – 16 Oct 2026 = all history loaded)
Verified with temporary `log.info` lines (removed from the final file):
- **19 signals** (9 long / 10 short). That works out to about 1.5 a week.
- All 19 are at or after 09:30, at or before 14:45, outside 12:30–13:30, and at or above min score.
- 1 signal fell on an expiry Tuesday (score threshold +10 applied, before 13:30).
- Expiry flag matched Tuesdays exactly.
- Every exit event matched its bar's high/low against the logged SL/T1/T2/T3. That covers SL hits, T1→BE, T2→trail, T3 exits, and square-offs on the 15:10 bar.
- Visual check (8 Oct short): SELL label with Entry/SL/T1–T3, entry/SL/target lines, T1/T2 event labels, and expiry-day shading on Tue 6 Oct.
- Dashboard fills every row.
- **Futures OI works intraday** on NSE:NIFTY1!: `NSE:NIFTY1!_OI` returns data (e.g. "Long unwinding −26.52K").

## Findings to flag (report vs. reality)
- **A. Volume is not required for a signal.** In the report's design, volume surge is only one of nine weighted factors (20/100). A breakout with *below-average* volume can still fire: 8 Oct's signal had RVOL 1.9, but 12 Aug's had RVOL 0.97. That conflicts with the stated goal "volume surge + sustained move". The new `Require volume surge as hard filter` toggle (default off, i.e. report spec) will be tested in Phase 3.
- **B. History is short.**
  - TradingView loaded only about 3 months of 5m data on your account (≈5,000 bars, 21 Jul – 16 Oct 2026). That gives about 19 signals on Nifty 5m.
  - That is far below the report's own "≥200 trades before trusting a win rate". Phase 2/3 results on this window will be statistically weak, and I will say so in the numbers.
  - Options: a plan with more bars, or Deep Backtesting (Premium).
- **C. Your chart shows the "D" (delayed) badge.** Per the report's caveat, delayed NSE data makes 1–5m live signals unusable. Check your TradingView data subscription before using this live.
- **D. The script is on your chart but not saved** to your TradingView account ("Untitled script"). Click **Save** in the Pine Editor if you want to keep it, or paste `nfce_indicator.pine` again later.
- **E. Cosmetic.** The dashboard covers the top-right of the chart, and the status line lists every input. Untick "Show dashboard" or change it in settings if it gets in the way.
