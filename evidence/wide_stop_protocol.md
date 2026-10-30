# Wider stops for stock 3m signals (registered 22 Oct 2026, evening, before any run)

**Why:** tonight's studies (`best_practice_tests_result.md`) found a gross edge of about +0.05R per trade against costs of about 0.3R. The stops sit only 0.3–0.4% from the entry, so the fixed costs are a third of the risk. With a stop k times wider, the same costs become about 1/k of that share. **Question:** does the edge survive when the cost share falls?

**Trades:**
- **Entries:** the stock 3m NFCE signals of `stock3m_protocol.md`: all F&O stocks with Upstox 3m history (about 210, `~/Downloads/nfce_data/hist3m_fo`), current costs, one lot of about ₹7 L notional.
- **Fills:** the next bar after the signal, the same as V0.
- **The only change is the exits.** For a signal with risk R (its own entry-to-stop distance):

| Config | Stop | Target | Square-off |
|---|---|---|---|
| **K2** | 2R from the entry | 2R, all out | the bar closing 15:15 |
| **K3** | 3R | 3R | the same |
| **K4** | 4R | 4R | the same |

- **Same walk as V0:** stop first when both are touched in one bar.
- **Results in units of the new risk:** net R = net points / (k × R).
- **Reference:** V0 (k = 1) is reported alongside.

**Family:** three tests, Bonferroni, so each needs one-sided p(day) < 0.0167.

**Pass (each config, each stage):** all three of
1. net R per trade > 0 after costs;
2. a day-block 95% interval above 0;
3. p(day) < 0.0167.

**Stages:**
1. **Train:** 2022–24.
2. **Validation:** 2025, only for configs that pass train.
3. **Final:** a one-shot 2026 (to 2026-10-20), only for configs that pass validation.

Every number is reported at every stage that is run.

**What a pass would mean:** a stop-width rule that held on unseen years after costs.
- **Live use:** it would go to a paper account first (WIDE already trades 2× stops, as options).
- **Never:** straight to more money.

**What a fail would mean:** the entries themselves carry no usable edge at any stop width tested. The next step would then be a different entry design, not different exits.
