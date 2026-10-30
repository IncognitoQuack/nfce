# Day-level profit booking: stop new entries once the day is good (registered 25 Oct 2026, evening, before any run)

**Why:**
- On 23 Oct the six accounts were +₹70,281 at 10:16 and closed at −₹3,080.
- Locking profit inside each trade made results worse (`profit_lock_result.md`).
- This tests the day-level version, used by many professional desks: stop opening new trades once the day has gone well, or once the day starts giving back its profit.
- Open positions keep their own stops and targets.

**Trades:**
- the stock 3m NFCE signals on 210 F&O stocks (current costs, one lot of about ₹7 L), with the live exits **V0** and the best exits **K4**;
- the same engine run, which now also records each trade's exit time (no rule changed).

**The day book:** each day, the trades in time order. One unit = 1R per trade (all trades the same size). Day P&L at a moment = the sum of net R of the trades **closed** by then. Open positions are not marked; that makes the rules react later, so it is conservative.

**Rules (block new entries for the rest of that day):**
- **DT, profit target:** once the day's closed P&L reaches **+3R**, take no new trade that day.
- **DG, give-back stop:** once the day's closed P&L has reached at least **+2R** and then falls to **half of its peak**, take no new trade that day.

**A trade counts if** its entry time is before the moment the rule triggered.

**Compare:**
- the mean day total (R per day) of each rule against the baseline (all trades), on the same days;
- worst day; 5th-percentile day; maximum drawdown.

**Pass (each rule × exit set; family of 4, Bonferroni, so p < 0.0125):** both of
1. the mean day total is above the baseline's, with the paired day-block bootstrap of the difference giving one-sided p < 0.0125;
2. the rule's own mean day total > 0.

The second condition keeps a rule that only "loses less" from being called profitable.

A softer outcome is reported separately but does **not** pass: the difference passes, but the rule is still negative. That would be a risk control, not a profit rule.

**Stages:**
1. **Train:** 2022–24.
2. **Validation:** 2025, only for passes, one look.
3. **2026 one-shot**, only after a validation pass.

**Use:**
- **A pass:** it goes into the accounts as a day rule.
- **A risk-control-only outcome on train and 2025:** reported to the owner to decide.
- **A fail:** reported; nothing changes.
