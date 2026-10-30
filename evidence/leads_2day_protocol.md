# Two leads from the 21–22 Oct live days: registered history tests (22 Oct 2026, evening, before running)

**Where the leads come from:** the introspection in `LIVE_DAY_2026-10-22.md` (58 live signals, 2 days). The 2 days themselves are NOT evidence; only the history below decides.

## H1: stock 3m signals, morning entries only
- **Live observation:** signals starting 10:00–11:59 made +0.18 / +0.21R per trade; 12:00–14:59 lost −0.30 to −0.97R.
- **Rule:** the `stock3m_protocol.md` V0 trades (`tools/stock3m_research.py`: current costs, one lot of about ₹7 L, all out at T1, stop first), restricted to **entry times before 12:00 IST**.
- **Data:**
  - **Primary:** all F&O stocks with Upstox 3m history, about 213 (`~/Downloads/nfce_data/hist3m_fo`, pulled 22 Oct).
  - **Secondary, reported separately:** only the stocks NOT among the original 50 (never used in any study).
- **Comparison:** the same trades without the time filter (all-day V0).

## H2: scanner, SELL side only
- **Live observation:** the scanner's SELL side (losers) made +0.77R and +0.25R per trade on the 2 days; the BUY side lost both days.
- **Rule:** `tools/scanner_research.py` rule G1 (top-5 gainers / losers by % change at the scan time; ATR stop, 1/2/3R ladder), **keeping only the SELL trades** (the losers), at 10:15, 11:15 and 13:15 separately and pooled.
- **Data:** the existing 5m data of the original study (50 stocks).
- **Comparison:** the BUY side and both sides.

## Stages and pass rule (both)
- **Train:** 2022–24.
- **Pass:** net R per trade > 0 after costs, AND the day-block 95% interval above 0.
- **Only on a pass:**
  - 2025 validation, same rule;
  - then a one-shot 2026 test, same rule.
- **A failure** at any stage ends the test. Every number is reported, at every stage that is run.

## What a pass would and would not mean
- **A pass:** a rule that held on unseen years after costs, eligible for a paper account first, never straight to more money.
- **A failure:** the 2-day pattern was the market's direction on those days, not a property of the signals.
