# CAL-1: calendar effects on NIFTY (turn of the month, pre-holiday), long NIFTY futures (registered Wed 28 Oct 2026, ~18:50 IST, before any result)

**Why:** the owner asked for a new search for something that really makes money. Nearly every intraday idea has
failed here after costs (~50 registered tests). The best-documented effects not yet tested are slow calendar effects:
- **turn of the month (TOM)**: Lakonishok & Smidt 1988; McConnell & Xu 2008; for India, Mangala & Sharma 2007 (Nifty 1994–2005) and Satish & Bheemanagouda 2023 (Nifty, Sensex 2007–2023);
- **pre-holiday**: Lakonishok & Smidt 1988; Ariel 1990. No Nifty-specific study was found.

Both trade ~12–20 times a year, so costs are small relative to the move.

## Data
NIFTY 50 daily bars: `nfce_data/daily_2006/NIFTY_1d.pkl` (2006-10-23 → 2016-10-21) + `nfce_data/daily/NIFTY_1d.pkl`
(2016-10-28 → 2026-10-28).
- Duplicate dates are dropped (the 2006–16 file repeats 2015-12-31); weekend bars are dropped.
- **Holidays are inferred** as weekdays with no bar, except inside the known data gap 2016-10-22..2016-10-27.
- Limitation stated now: a Diwali Muhurat bar, if present, makes that holiday look like a trading day (about 1 event a year).

## Trades (long only; returns from the index close; traded as NIFTY futures)
- **C1 TOM:** day −1 = the month's last trading day. Buy at the close of day −2, sell at the close of day +3 (the 3rd trading day of the next month). One trade a month.
- **C2 pre-holiday:** buy at the close of the trading day before a pre-holiday session, sell at the close of the pre-holiday session (the last trading day before an inferred holiday). When C2 overlaps C1 it is still counted in C2; the two are separate tests.

## Costs per trade (deducted in bp of notional)
- **Transaction costs:** `nfce/costs.futures_cost_points` (CURRENT regime, 1 lot of 65, 2 orders) plus 2 bp of slippage per side.
- **Futures carry:** a long future loses the basis as it converges, charged at 6.2%/yr × calendar days held.
- Using the current (higher) costs on the old years is deliberately conservative.

## Family and pass rule
Two tests (C1, C2), Bonferroni: each needs, on its stage:
1. mean net return per trade > 0;
2. a bootstrap 95% CI (10,000 resamples of trades, seed 20261028) above 0;
3. one-sided t-test p < 0.025.

## Stages (no peeking)
- **Train** 2006-10-23 → 2015-12-31.
- **Validation** 2016-01-01 → 2020-12-31, only for tests that pass train.
- **Final** 2021-01-01 → 2026-10-28, ONE shot, only for tests that pass validation.

Reported at every stage: n, win %, mean gross and net (bp), CI, p, the share of years positive, and the worst trade.

## Use
- A test that passes all three stages becomes a paper sleeve, with the owner's OK. That means a new paper account (or the MAN account under the owner's control) trading 1 lot of NIFTY futures on the dates.
- A fail is reported plainly. Nothing is re-tuned: the hold window, the entry day and the costs are fixed above.
