# Meta-labeling for stock 3m signals (registered 22 Oct 2026, 17:40 IST, before any run)

**Source:** `best_practices_review.md` row 10 (López de Prado: a secondary model decides which primary signals to take). The primary signals stay exactly as they are; the meta-model can only **skip** trades.

**Trades:**
- the `stock3m_protocol.md` V0 trades on all F&O stocks with Upstox 3m history (about 213; `tools/stock3m_research.py`, current costs, one lot of about ₹7 L, all out at T1, stop first);
- the same trade list as `leads_2day_protocol.md` / `best_practice_tests_protocol.md`.

**Label:** net R after costs > 0.

**Features** (known at the entry time; nothing from later):
1. minutes since 09:15;
2. side (+1 BUY, −1 SELL);
3. stop distance as % of the entry price;
4. cost share of the risk;
5. NIFTY state: +1 / −1 / 0, aligned with the side or not. From the last completed NIFTY 5m bar vs the day's open (`best_practice_tests_protocol.md`); missing → 0;
6. India VIX: the last completed 3m close at or before the entry;
7. weekday;
8. same-direction trades across all stocks with entry times in the previous 30 minutes (only earlier trades).

**Model:**
- **Training:** scikit-learn `HistGradientBoostingClassifier`, default settings, `random_state=0`, fitted on **2022–2023 only**.
- **Threshold:** chosen on **2024** (purged: a different year) as the probability cut that maximises the mean net R per trade among cuts leaving at least 300 trades, searched over 0.40, 0.42 … 0.70.
- **Fixed afterwards:** model and threshold are frozen after 2024.

**Validation (one look):** 2025. The rule takes a trade when its predicted probability is at least the threshold. **Pass:** all three of
1. net R per trade > 0 after costs;
2. a day-block 95% interval above 0;
3. one-sided p(day) < 0.05.

**Only on a pass:** a one-shot 2026 test (trades up to the end of the NIFTY data), same rule.

**Reported:**
- the 2024 threshold search;
- the 2025 and (if run) 2026 results, with every number;
- the base rate and the AUC on each period.

**Expectation, stated in advance:** the earlier ML direction study (1.09 M samples) found no skill (AUC 0.50–0.54). A meta-model on these features may fail too; that would be reported as plainly as a pass.
