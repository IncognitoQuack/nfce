# Live forward test of signal variants (registered 22 Oct 2026, 13:40 IST, before any qualifying signal)

**Requested by:** the admin (S chat, 13:37): "test your few tricks and theories to see if they work and make paper trades based on that".

**Where the ideas come from:** the losses of 21–22 Oct. Those two days are NOT test data for these ideas. Only signals that fire **after 13:45 IST on 22 Oct 2026** count, plus every later session.

## Signals covered
- Every `stock3m` signal.
- Every NIFTY/SENSEX engine signal (book `executable`).

Each is taken as it was alerted: side, entry, SL, T1–T3 (all 1R apart).

## Variants (each signal is scored under every variant)
| Id | Rule |
|---|---|
| V0 | As live: SL and targets as alerted. Whole-lot ladder 40/30/30 (one lot: all out at T1), breakeven after T1, square-off 15:15 |
| V1 wide stop | SL distance ×2; T1/T2/T3 at 1/2/3 × the new distance; otherwise as V0 |
| V2 confirmation | Enter only if, within 15 minutes after the signal, price trades 0.5 × R beyond the alerted entry in the signal's direction. Fill at that price. SL and targets as alerted (so the risk to the SL is 1.5R). No confirmation within 15 minutes: no trade |
| V3 cluster cap | V0, but within any 30-minute window take only the first 2 signals of the same direction (time order; ties by alert id) |
| V4 time stop | V0, but exit at the close of the 30th minute after entry if neither SL nor T1 has been hit |

## Scoring
- **Prices:** 1-minute candles from Upstox (equity or index spot, the instrument the alert's levels are on).
- **Fills:** the next minute's open after the signal minute. A stop inside a minute's range is taken before a target in the same minute.
- **Costs:**
  - one lot of the stock or index future: `bridge/costs.py` at the 2026 rates;
  - plus half the median bid/ask spread of that future at the entry and the exit, from the minute quotes recorded in `nfce_bridge/data/study_quotes_*.db` (the median of that day if the minute is missing).
- **Reported per variant:** n, wins, mean R after costs, total rupees, and the share of signals skipped. Every variant, every session, including bad results.

## Decision rule (fixed now)
- No variant changes anything live until it has at least 100 qualifying signals AND passes the same test on 2022–24 (train), 2025 (validation) and 2026 (one shot), at current costs, on day means.
- Fewer than 30 signals: report the numbers and draw **no conclusion**.
