# Reversed stock signals: protocol (registered 27 Oct 2026, ~14:45 IST, before the run)

**Question (admin, 27 Oct 12:03):** "Are the signals reversed?" If the stock 3m engine is systematically wrong, taking the OPPOSITE side of every signal should make money after costs.

**Data and signals:** exactly the stock 3m run of `stock3m_protocol.md` / `wide_stop_result.md` (210 F&O stocks, Upstox 3m, `Params(instr="STOCK")`, current 2026 costs, one futures lot of about ₹7 L, `FRICTION` 2 bp). One engine run produces both the original V0 rows and the reversed rows.

**Reversed rule (REV):** at the same entry price and time, take the opposite side. Its stop is the original target and its target is the original stop (1R each). Exit at the 15:15 bar otherwise. Costs are computed by the same futures cost function. Implementation: a `walkers` entry in `stock3m_research.trades`, walking with `-side`. The returned exit price is mirrored (2·entry − px), so the existing gross formula gives the reversed P&L. The cost uses that mirrored price, a difference of under 0.1 bp, which is stated here.

**Stage:** train 2022–24 only. REV must pass all of the following:
- net R per trade > 0;
- the 95% day-block bootstrap interval lower bound > 0;
- one-sided day-block p < 0.05.

**Only if it passes:** validation on 2025, then a one-shot final on 2026-01-01..2026-10-20.

**Prediction written down before running:** FAIL. The original's gross is +0.051R, so the reversed gross should be about −0.05R. The costs are the same ~0.32R, so net about −0.37R per trade.

**Reported in any case:** n, win %, gross R, net R, day-block CI, p, alongside V0 from the same run.
