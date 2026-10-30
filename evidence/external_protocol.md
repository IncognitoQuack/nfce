# Protocol: candidates from the ChatGPT and Gemini research reports (20 Oct 2026, ~02:10 IST, before any result)

**Sources:**
- `docs/research_round2/deep-research-report.md` (ChatGPT)
- `docs/research_round2/Intraday NIFTY Trading Strategies.pdf` (Gemini)

**Verified before testing:**
- **Medidala repository:** rules and numbers match the ChatGPT report. The repository's own *train* Sharpe was 0.004 (test 0.691), with costs of ₹75 per round trip plus 2 points per side.
- **Zarattini et al. 2024:** the abstract figures match the Gemini report.

## Data, splits, costs
- **Data:** Upstox 5m spot, 3 Jan 2022 – 31 Jul 2026, regular session.
  - NIFTY and BANKNIFTY are traded as a proxy for front-month futures (no basis, no roll).
  - VWAP uses the summed volume of five heavyweights.
  - Daily bars are built from the 5m bars.
- **Splits:**
  - TRAIN: 2022–2024
  - VALIDATION: 2025
  - FINAL: Jan–Jul 2026, run once
- **Costs: CURRENT (18 Oct 2026) schedule for every trade, in every split.** Futures fees for 1 lot, plus 4 ticks friction per side, plus ₹20 per order. This is the cost of trading the rule from now on.
- **Fills:**
  - signal on a completed bar → fill at the next bar's open;
  - stop-entries → fill at max(open, level) for buys, min(open, level) for sells;
  - stops → at the stop, or at the open if the bar gaps through it;
  - when a stop and a target are both touched in one bar → the stop.
- **R:** the stop distance where a rule has a stop. Otherwise 0.25 × daily ATR14 of the previous days (S2, S3, S8).

## Candidates (exact rules)
| ID | Rule |
|---|---|
| S1 sigma | Session anchor = expanding mean of 5m closes from 09:15; dev = close − anchor; z = dev / std(dev, last 12 bars, ddof=1). Long if z ≥ 2.5 and close > EMA200 (continuous); short if z ≤ −2.5 and close < EMA200. Signal bars close 09:30–14:30. Exit: z crosses 0 (completed bar → next open), stop 1.5 × daily ATR14 (Wilder, previous days), or the 15:25 bar close. One position at a time; re-entry allowed. |
| S2 noise / S2L noise-long | σ(hm) = mean over 14 previous sessions of \|close(hm)/open(09:15) − 1\|. Upper = max(open, prev close) × (1+σ); Lower = min(...) × (1−σ). Checkpoints: bars closing 09:45, 10:15 … 14:45. Flat and close > Upper → long next open; close < Lower → short (S2 only). Exit when a 5m close is below max(Upper, VWAP) for longs (min(Lower, VWAP) for shorts), at the next open; hard exit at the 15:25 close. At most 2 trades a day. |
| S3 williams-pd | Long only. Buy stop at today's open + 0.5 × (prev high − prev low), active on bars 09:15–15:10. No stop, no target; exit at the 15:25 close. One trade a day. |
| S4 williams-dsr | DSR = max(\|H(t−3) − L(t−1)\|, \|H(t−1) − L(t−3)\|). Buy stop at open + 0.5 DSR, sell stop at open − 0.5 DSR, active on bars 09:20–14:30. Stop = today's open. Target = entry ± 2 × DSR (4R). Exit at the 15:25 close. One trade a day; a bar touching both levels means skip the day. |
| S5 nr7 | Day t−1 range strictly below each of the 6 previous ranges. Day t: buy stop at H(t−1), sell stop at L(t−1), first trigger only. If the open is beyond the trigger but not beyond the target, enter at the open; if beyond the target, skip the day. Stop = the opposite boundary. Target = ± A (mean of the last 7 daily ranges). Exit at the 15:25 close. |
| S5c nr7-or-idnr4 | Day t−1 is NR7, or (an inside day and the narrowest of 4), **and** its range ≥ 0.35 × ATR14. Otherwise as S5 (no stop-and-reverse). |
| S6 oops | Gap down: open ≤ L(t−1) − 0.15% × C(t−1) and VIX(t−1 close) ≥ 15 → buy stop at L(t−1), on bars 09:20–11:15. Stop = today's low before entry − 1 tick. Target = prev midpoint. Exit at the 15:25 close. Gap up is the mirror. One trade a day. |
| S7 weekend-holiday ORB | Eligible session: the first session after a weekend (gap ≥ 3 calendar days, no weekday missing) or after a weekday holiday. OR = 09:15–09:30. After 09:30, first close beyond the OR → next open, stop on the other side. Weekend sessions: last signal 10:10, exit at the 10:15 close. Holiday sessions: last signal 09:40, exit at the 09:45 close. |
| S8 morning-0.5% | r = close(09:45 bar) / open(09:15) − 1. If \|r\| > 0.5%, enter in that direction at the 09:45 bar's open; exit at the 15:15 close. No stop. (The underlying signal of ChatGPT #2; its option payoff can't be tested without option history.) |
| S9 late-momentum (no NGE) | ONFH = close(09:45)/C(t−1) − 1, ROD = close(15:00)/C(t−1) − 1. Same sign and \|ROD\| ≥ 0.65% → enter at the 15:00 bar's open. Stop 0.30% from entry; exit at the 15:25 close. (Gemini #4 without its NGE filter, for lack of OI history: a necessary-condition test.) |

**Total:** 11 rules × 2 indices = **22 configurations**. Nothing is added after results are seen.

## Selection
1. **TRAIN:** ≥ 30 trades, net R > 0, and positive in ≥ 2 of 3 years.
2. **VALIDATION:** net R > 0 and one-sided p < 0.05 (day-clustered t on daily mean R), on ≥ 20 trades. Carry at most the top 3.
3. **FINAL** (one shot) **PASS:**
   - net R > 0;
   - day-block 95% lower bound > 0;
   - PF ≥ 1.15;
   - ≥ 20 trades.
4. **Outcome:** a PASS becomes a registered live paper experiment, not a recommendation. A FAIL at any stage stops that candidate.

**Not testable here (reported, not tested):**
- option-premium strategies: short straddle, 0DTE iron condor, OI unwinding, the option leg of ChatGPT #2, and the 2:1 ratio spread (also rejected for its naked tail risk);
- the NGE filter of Gemini #4.

These need historical option prices or OI, which the bridge starts recording live (R1).
