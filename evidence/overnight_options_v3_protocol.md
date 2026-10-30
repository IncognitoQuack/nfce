# Overnight NIFTY iron fly, v3 (= GS-OVN-1 v3): forward paper test, a NEW sample alongside v2

**Registered** 27 Oct 2026, evening, after the close. The first v3 session is 28 Oct 2026 (entry 15:20, exit 29 Oct from 09:20), so **no v3 outcome exists at registration.**
**Owner (27 Oct):** "register OVN v3 using the put-call-parity forward after 15:15, as a new sample alongside v2."

## Why v3
- Since NSE's closing auction (from 3 Aug 2026), cash trading in F&O stocks stops at 15:15. The NIFTY index then stops updating, while NIFTY options trade to 15:40.
- On 27 Oct the chain's spot sat at 22,760.75 from 15:15:48, while put-call parity at 15:20 implied about 22,785.
- v2 (`overnight_options_v2_protocol.md`, SHA `18fce1fa…de68`) centres the fly on the strike nearest that frozen spot.
- **v3 centres it on the strike nearest the options market's own forward.** The forward also includes the expiry's carry, which is the right centre for a straddle in any case.

## Rules: v2 VERBATIM, except rule 7's reference price
Everything in `overnight_options_v2_protocol.md` applies unchanged: sessions and calendar, data, causal inputs (ATR14, VIX), skips (VIX > 25 or 5-session rise > 20%, events, blocking), regime size, the entry snapshot [15:20:00, 15:21:00), the expiry rule, wings (w = ceil(ATR14 / step) × step), the structure, quotes, fills, fees, the exit-fee reserve, sizing (₹5,000 budget including fees, ₹10 L book), the exit, unresolved handling, units, the widened series, and the judgement (pilot 60 / validation 60 / final N, α 0.003125, the same bootstrap).

**Rule 7 in v3:** the reference price S is the **put-call-parity forward F** of the chosen expiry in the entry snapshot. K is then the listed strike nearest F (a tie goes to the lower strike), and the wings are set around K as in v2. The stress grid for the exit-fee reserve is centred on F.

**The forward F, exactly:**
1. In the entry snapshot, for the chosen expiry, take the **3 listed strikes nearest the chain's spot**.
2. For each that has valid quotes on both its call and its put (bid > 0, ask > 0, ask ≥ bid): **F_k = k + mid(call) − mid(put)**, where mid = (bid + ask) / 2. There is no discounting: it changes F_k by well under one point at a week's expiry.
3. **F = the median of the available F_k.**
4. **No valid pair:** the session is *no forward: not entered* (covered; P&L 0).

## Sample, stages, verdicts
- **A new, separate sample from 28 Oct 2026.** v2 continues as registered. Neither series is merged with the other or used to choose between them after the fact.
- v3 has its own pilot (the first 60 sessions from 28 Oct), validation and final, exactly as v2, and its own GS claim slot at the final.
- **Reported in addition (descriptive):** the gap between F and the chain spot at entry (points), and whether K differs from v2's K on the same day.
- **OPX-1** stays tied to v2 as registered. An OPX on v3 would be a new registration.

## Not allowed
Changing the forward definition, its strikes or the fallback after seeing any result. Switching between v2 and v3 based on results.
