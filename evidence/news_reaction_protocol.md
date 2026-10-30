# News reaction of F&O stocks to NSE corporate announcements: forward study (registered 26 Oct 2026, before the first scored session)

**Why:**
- News is the usual reason a stock is "in play".
- The research note (`research_how_systems_are_built.md`, test 5) and `study2_result.md` explain why news can only be tested **forward with real timestamps**: an LLM or a back-dated archive would leak the outcome.
- Since 26 Oct the bridge logs every NSE corporate announcement with its **dissemination time** and the time **our recorder saw it** (`nfce_bridge/data/study_news_YYYYMMDD.db`). It also logs minute quotes of every F&O stock (`study_quotes_YYYYMMDD.db`).

**Code:** `nfce_engine/tools/news_reaction.py`; tests `nfce_engine/tests/test_news_reaction.py`. Read-only.

## Events
- **An event counts if:**
  - the stock has cash-equity quotes in that day's quote file (= in the F&O list the recorder follows; the news file's own `fno` flag is reported but not used);
  - it was disseminated in market hours, **09:15 ≤ t0 ≤ 15:00**.
- **Announcements outside market hours** are a gap/overnight question. They are logged for a later study and not used here.
- **Groups** (from NSE's category):

| Group | NSE categories |
|---|---|
| results | Financial Results, Outcome of Board Meeting |
| orders | Bagging/Receiving of orders/contracts |
| press release | Press Release |
| analyst meet | Analysts/Institutional Investor Meet/Con. Call Updates |
| other | everything else |

## Part A: reaction (descriptive, no α)
- **Abnormal return** AR(h) = the stock's mid return from the last quote at or before t0 (no older than 3 minutes) to the first quote at or after t0 + h, **minus** NIFTY futures' mid return over the same times, for h = 5, 15, 30 and 60 minutes.
- **Reported:**
  - mean |AR| and mean AR by group and horizon;
  - continuation vs reversal: the share of events where AR(60) has the same sign as AR(5), and the regression slope of AR(60) − AR(5) on AR(5);
  - the recorder's lag (seen − t0).

## Part B: one trading rule, fixed now (R1)
- **Trigger:** |AR(5)| ≥ **0.40%**. Trade in its direction.
- **Entry:** at the first quote at or after **max(t0 + 5 min, the time our recorder saw the announcement)**: buy at the ask, sell short at the bid.
- **Exit:** at the last quote at or before **min(t0 + 60 min, 15:20)**, at the bid (long) or the ask (short).
- **Costs:** the spreads are paid through those quotes, plus cash-equity intraday fees on ₹3 L (`study2.equity_intraday_fees`).
- **One event at a time:** a stock with several events within 60 minutes trades only the first.

## Sample and judgement
- **26 Oct 2026 is the pilot:** used only to build and check the method (no rule chosen on it), and excluded from the claims.
- **Judged once**, at the first close with **≥ 100 R1 trades and ≥ 30 sessions** from 27 Oct.
- **R1 passes if all three hold:**
  1. mean net bp per trade > 0;
  2. a one-sided t-test on the per-session mean net bp gives p < 0.05;
  3. the mean is still > 0 with every spread widened 1.5×.
- **Part A is descriptive.** If it suggests a different rule (another N, threshold, or the fade), that rule needs **its own new protocol and fresh sessions after that date**. It is never re-scored on the sessions it came from.

## What it would and would not mean
- **A pass** would justify a registered paper account trading news reactions, never straight to money.
- **A fail** means minute-level reactions to NSE filings are priced before we can act on them, or do not pay after costs.
- **Limitation:** minute quotes, not ticks. The first minute after a filing is not visible, which is why R1 waits 5 minutes.
