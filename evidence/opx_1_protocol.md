# OPX-1: range-gated overnight NIFTY iron fly (forward paper pilot). Protocol

**Registered** 27 Oct 2026, evening, after the close. The first session covered (27 Oct, entry 15:20) exits on 28 Oct from 09:20, so **no outcome of any covered session is known at registration.**
**Owner's request (27 Oct):** "design the options-premium module (defined risk, range-model gated) with a locked protocol, as a paper pilot."

## Why this design (written before any data)
- **Both outside research reports (27 Oct) rank option premium first.** The best evidence (Muravyev & Ni 2020, *JFE*; Bhat, Pandey & Rao 2024, *J. Futures Markets*, Nifty 2017–20) finds short-option returns favourable **overnight** and not intraday. So OPX-1 sells premium **overnight only**. An intraday short-premium design would go against that evidence and is not built.
- **The vehicle is OVN v2** (`overnight_options_v2_protocol.md`, SHA `18fce1fa…de68`), unchanged: the NIFTY iron fly at 15:20, wings at 1 × the previous session's ATR14, the ₹10 L book, **₹5,000 per structure including fees** (defined risk: the maximum loss is the wing width minus the credit, plus fees), the VIX and event gates, one structure at a time, fills at bid/ask, an exit-fee reserve, and no last-price marks.
- **OPX-1 adds ONE thing: a gate.** It takes the OVN v2 structure only on nights when implied volatility is rich against the system's own volatility forecast (the range model; R² 0.31–0.37 out of sample). This asks the question both reports raised: **does conditioning on a forecast add value over selling the same exposure unconditionally?** Ungated OVN v2 runs in parallel as the control.

## The gate (causal: every input is known by the 15:20 entry)
1. **Forecast:** the mean over session d of `exp(q50)` of the **ENS** model's NIFTY rows in `nfce_bridge/data/nfce.db` table `range_forecasts`, for all bar closes on d (09:45–14:15). That is the expected next-hour high-low range as a fraction, F(d).
2. **Forecast volatility, annualised:** σ̂(d) = F(d) / 1.596 × √(252 × 6.25) × 100, in %.
   - 1.596 = √(8/π), the expected range of a Brownian path per unit σ√T.
   - The annualisation uses trading time.
   - **The ratio below is a regime index, not a calibrated volatility premium.** Implied volatility also prices the overnight and weekend.
3. **Implied volatility:** IV(d) = the mean of the chain's `iv` for the K call and the K put of the OVN v2 structure (same expiry, same strike K) in the OVN v2 entry snapshot (the first snapshot in [15:20:00, 15:21:00)).
4. **Ratio** R(d) = IV(d) / σ̂(d). **The gate is on if R(d) ≥ 1.50.** The threshold was chosen before any data, as "implied at least 50% above the forecast". On 27 Oct at 14:40 a rough reading was about 1.36; that reading does not include the 15:20 snapshot and played no part in choosing 1.50.
5. **Gate unknown** (no ENS rows for d, or no IV for either leg): no OPX entry; the session counts against OPX coverage.

## Series
- **u_opx(d) = u(d) if the gate is on and OVN v2 entered on d; otherwise 0.** u(d) is the OVN v2 daily unit (net ₹ / ₹5,000).
- `units_widened` is gated the same way.
- Unresolved OVN v2 structures carry their worst / best bounds, as in OVN v2.
- **Control:** the OVN v2 series u(d), as registered.

## Stages (the same windows and statistics as OVN v2; `gs/evaluate.py`, stationary block bootstrap, block 5, 50,000 replicates, seed 20261026)
1. **Pilot: the first 60 exchange sessions from 27 Oct 2026.**
   - **Futility:** if the one-sided 90% upper bound of mean u_opx is < 0, OPX-1 is closed (FAIL).
   - **Report:** the number of gate-on nights; for OVN v2 entered nights, the mean u on gate-on vs gate-off nights and their difference with a bootstrap 90% CI (descriptive); the correlation of R(d) with u(d).
2. **Validation: the next 60 sessions, rules frozen.** Continue only if all hold:
   - total gated net ₹ > 0;
   - total gated widened net ₹ > 0;
   - the mean u per gated entered night > the mean u per ungated entered night over the same sessions;
   - ≥ 15 gated structures;
   - coverage ≥ 90%.
   Otherwise FAIL (or INCONCLUSIVE if there are fewer than 15 gated structures).
3. **Final:** length N from the OVN v2 formula with σ = the pilot SD of u_opx. One look at **α = 0.003125** (one of the 16 GS claim slots). The same PASS conditions as OVN v2 with u_opx in place of u, **plus** the gated-minus-ungated mean per entered night > 0 at the same α. If N cannot be completed within 5 calendar years, the verdict is INFEASIBLE.

## Risk controls (firm-style; reporting, not sample changes)
- **Inherited from OVN v2:** defined risk, a hard per-structure cap of ₹5,000 including fees (halved when VIX is above 20), VIX > 25 or a 5-session rise above 20% means skip, event days are skipped, one structure at a time, unresolved legs block new entries.
- **Max-loss alarm:** a structure losing at least 90% of its budget is reported to the owner the same morning, with the overnight gap in ATR units. It stays in the sample. The alarm never removes or pauses sessions, because a results-dependent pause would bias the test.

## Known limitation, recorded before any result
Since NSE's closing auction (from 3 Aug 2026), the index spot freezes at 15:15, while NIFTY options trade to 15:40. OVN v2 picks K from the chain's spot at 15:20. On 27 Oct that spot was 22,760.75, while put-call parity implied about 22,785, so the fly can be centred one strike off the forward.
- OPX-1 inherits OVN v2 exactly as registered and does not fix this.
- A forward-based OVN v3 would be a new registration with a new sample, and OPX-1 would follow it only as a new version.

## Not allowed
Changing the threshold, the forecast model (ENS), the inputs, or the windows after seeing any result. Re-running with another threshold and reporting the best one. Dropping sessions.
