# Index-alignment filter for stock 3m signals (registered 22 Oct 2026, evening, before running)

**Source:** `best_practices_review.md` row 7 (regime / market alignment, standard in published systematic practice). On 22 Oct, 16 of 20 stock signals were SELLs into a rising index.

**Trades:** the `stock3m_protocol.md` V0 trades: `tools/stock3m_research.py`, current costs, one lot of about ₹7 L, all out at T1, stop first. Data: all F&O stocks with Upstox 3m history (about 213, `~/Downloads/nfce_data/hist3m_fo`).

**Index state at a signal:**
- **Bar:** the last NIFTY 5-minute bar (spot, `hist50/NIFTY_5m.pkl`) that **closed at or before** the trade's entry time.
- **Compare** its close with the same day's NIFTY open (the open of the 09:15 bar).
- **No completed NIFTY bar that day:** the trade is excluded from H3 and H4.
- **Range:** the NIFTY data ends on 2026-07-31, so the 2026 stage (if reached) uses trades up to that date.

**Tests (one family; Bonferroni, so each one-sided p on day means < 0.025):**
- **H3, aligned:** keep a SELL only if NIFTY is below its day open, and a BUY only if NIFTY is above it.
- **H4, aligned and morning:** H3, and the entry time is before 12:00 (H1's filter).

**Comparisons reported:**
- V0 (all trades);
- the counter-aligned trades (the ones H3 drops);
- H1 alone, for reference (its own registered rule is in `leads_2day_protocol.md`).

**Pass (each test):** all three of
1. net R per trade > 0 after costs;
2. a day-block 95% interval above 0;
3. one-sided p(day) < 0.025.

**Stages:**
- **Train:** 2022–24.
- **Only on a pass:** 2025, then a one-shot 2026, same rule.
- **Reported:** every number.

**What a pass means:** a filter that held on unseen years after costs. It would go to one paper account first.
