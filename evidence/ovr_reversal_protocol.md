# OVR-1: high-VIX, news-free overnight loser reversal in F&O stocks. Protocol

**Registered** 27 Oct 2026, ~14:45 IST, before any run. Source: the Gemini research report of 27 Oct, Strategy 3 (Nagel 2012; Da, Liu & Schaumburg 2014; Lou, Polk & Skouras 2019; Avramov, Chordia & Goyal 2006). It is adapted only where our data forces it, and each adaptation is listed.

## Rule (decided at the bar closing 15:15, using only data up to then)
1. **VIX gate:** India VIX at that bar ≥ the 70th percentile of the previous 252 daily VIX closes.
2. **News purge:** drop any stock with a results board meeting from t−3 to t+1 calendar days (`results_calendar.csv`; the dates are announced in advance).
3. **Liquidity filter:** drop the 30 stocks with the largest 20-day average rupee volume (a proxy for the NIFTY top 30; we have no constituent history). Of the rest, keep the more illiquid two-thirds by 20-day Amihud illiquidity (mean |daily return| ÷ rupee volume).
4. **Signal:** the intraday return from the 09:15 open to the 15:15 close, minus the equal-weight mean of all 213 stocks over the same window. It must be ≤ −2.5%. Day volume to 15:15 ≥ 1.5× its 20-day median (to the same time).
5. **Entry:** buy the 3 most negative (fewer if fewer qualify) at the 15:15 close.
6. **Exit:** at the close of the next session's bar closing 09:45. No stop.
7. **Cost:** 15 bp per round trip per position (stock futures; overnight futures pay no delivery STT).
   - The prices are cash 3-minute bars, used as a proxy for the futures (no futures history).
   - Adaptations: market-relative instead of sector-relative; no passive-fill filter (no historical book); exit at the 09:45 close instead of a 09:16–09:45 passive unload.

## Stages and verdict
- **Train 2022–24.** PASS requires all of:
  - net bp per trade > 0;
  - the 95% day-block bootstrap lower bound > 0;
  - one-sided day-block p < 0.05;
  - at least 60 trades.
- **Validation 2025** only if train passes; the same criteria.
- **Final 2026-01-01..2026-10-20, one shot,** only if validation passes.
- **Also reported:** the unconditional version (VIX gate off), for context only. It is not tested for a pass.

## Prediction written down before running
Gemini claims +18 to +43 bp net per trade. That figure was transferred from US studies, not measured on NSE. I expect a much smaller gross effect on NSE F&O stocks, and few qualifying nights (the VIX gate plus a −2.5% threshold). Likely INCONCLUSIVE or FAIL on sample size.
