# Does the opening gap (what GIFT Nifty foretells) carry usable information? (registered 25 Oct 2026, before any run)

**Why:** the owner asked whether GIFT Nifty and similar pre-market inputs would help.
- **What GIFT Nifty is for:** it trades overnight on NSE IX, and its main value is a forecast of NIFTY's opening gap.
- **Why the actual gap can stand in for it:** the NFCE engine acts only from 09:30. By then the actual gap (09:15 open vs the previous close) is known exactly.
- **So:** if the actual gap carries no usable information, GIFT Nifty cannot add any for this system.
- **Data limit:** GIFT Nifty history is not in the Upstox feed and is not freely available.

**Data:**
- NIFTY spot daily candles 2016-10 → 2026-10 (`~/Downloads/nfce_data/daily/NIFTY_1d.pkl`);
- the stock 3m trades already computed (V0 and K4 exits, 210 F&O stocks, current costs).

**Gap:** g = NIFTY open / previous close − 1.

**G1, the index day trade:**
- **Rule:** if |g| ≥ 0.3%, take NIFTY futures in the gap's direction at the open and exit at the close. Return = sign(g) × (close / open − 1).
- **Cost:** 2 × 4 bp per round trip (index futures: fees about 3 bp per side + about 1 bp half-spread).
- **The opposite rule (fade)** is reported alongside. The pass rule applies to G1 only; the fade is reported, not tested.
- **Pass:** mean net daily return > 0, one-sided t-test p < 0.05, and a 20-day-block bootstrap 95% CI above 0.

**G2, a filter for stock 3m signals:**
- **Rule:** keep a trade only if its side equals sign(g) on its day and |g| ≥ 0.3%.
- **Exits:** V0 and K4.
- **Pass:** net R > 0 after costs, a day-block CI above 0, p(day) < 0.05.

**Family:** G1, G2-V0, G2-K4: Bonferroni, so each needs p < 0.0167.

**Stages:**
1. **Train** (G1: 2019–24; G2: 2022–24).
2. **Validation 2025**, only for passes.
3. **2026 one-shot**, only after a validation pass.

**Use:**
- **A pass:** the gap (and so GIFT Nifty, as an earlier read of it) becomes a filter in a new paper account.
- **A fail:** GIFT Nifty is not added. The morning brief shows the actual gap as information.
