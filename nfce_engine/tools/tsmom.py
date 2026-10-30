"""Time-series momentum on F&O stock futures, weekly (../evidence/tsmom_protocol.md).

  python tools/tsmom.py <daily folder> --stage train
  python tools/tsmom.py <daily folder> --stage validation --configs TS120 ...   (only configs that passed train)
  python tools/tsmom.py <daily folder> --stage final --configs ... --i-accept-one-shot

No look-ahead: the signal and the volatility at a decision day use closes up to that day; the trade happens at the
next trading day's open and is held to the open after the next decision (open-to-open returns).
"""
from __future__ import annotations

import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

STAGES = {"train": (date(2019, 1, 1), date(2024, 12, 31)), "validation": (date(2025, 1, 1), date(2025, 12, 31)),
          "final": (date(2026, 1, 1), date(2026, 10, 21))}
CONFIGS = {"TS60": 60, "TS120": 120, "TS250": 250}
COST, STRESS = 0.0008, 0.0012
VOL_N, TARGET, CAP = 60, 0.01, 3.0
GAP_LO, GAP_HI = -0.30, 0.40
P_MAX, SHARPE_MIN = 0.05 / 3, 0.5
INDEXES = {"NIFTY", "BANKNIFTY", "INDIAVIX"}


def load(folder: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.Series]:
    opens, closes = {}, {}
    for f in sorted(folder.glob("*_1d.pkl")):
        sym = f.stem[:-3]
        d = pd.read_pickle(f)
        d = d[(d["close"] > 0) & (d["open"] > 0)]
        d = d[~d.index.duplicated(keep="first")]          # 2006-16 data repeats 2015-12-31 once (identical rows)
        if sym == "NIFTY":
            nifty = d
        if sym in INDEXES:
            continue
        opens[sym], closes[sym] = d["open"], d["close"]
    cal = nifty.index                                       # the trading calendar
    o, c = pd.DataFrame(opens).reindex(cal), pd.DataFrame(closes).reindex(cal)
    # 25 Oct bug fix: NIFTY's calendar has special sessions (Muhurat / Saturday) with no stock candles; each one made
    # the 60-day volatility NaN for most stocks for ~3 months, silently dropping them. Keep only days on which at
    # least half of the already-listed stocks traded.
    listed = (c.notna().cumsum() > 0).sum(axis=1)
    keep = ~((c.notna().sum(axis=1) < 0.5 * listed) & (listed > 20))
    return o[keep], c[keep], nifty["open"].reindex(cal)[keep]


def weeks(cal: pd.DatetimeIndex) -> list[tuple[int, int, int]]:
    """(decision index, entry index, exit index): decision = last trading day of each week."""
    ic = cal.isocalendar()
    iso = pd.Series((ic["year"].astype(str) + "-" + ic["week"].astype(str)).to_numpy(), index=range(len(cal)))
    dec = [g.index[-1] for _, g in iso.groupby(iso.values, sort=False)]
    out = []
    for a, b in zip(dec, dec[1:]):
        if a + 1 < len(cal) and b + 1 < len(cal):
            out.append((a, a + 1, b + 1))
    return out


def expiry_in(cal: pd.DatetimeIndex, i0: int, i1: int) -> bool:
    """The holding window [i0, i1) contains a monthly expiry: the month's last Tuesday or last Thursday (the expiry
    weekday changed in 2025); charging the roll for either is the conservative choice."""
    for t in cal[i0:i1]:
        nxt = t + pd.Timedelta(days=7)
        if t.weekday() in (1, 3) and nxt.month != t.month:
            return True
    return False


def backtest(opens: pd.DataFrame, closes: pd.DataFrame, L: int | None, cost: float, long_only: bool = False) -> pd.DataFrame:
    cal = closes.index
    rets = closes.pct_change(fill_method=None)
    vol = rets.rolling(VOL_N, min_periods=VOL_N).std()
    hist = closes.notna().cumsum()
    gap = opens / closes.shift(1) - 1
    rows, prev = [], pd.Series(0.0, index=closes.columns)
    need = (L or 0) + VOL_N
    for d, e, x in weeks(cal):
        c_now = closes.iloc[d]
        ok = c_now.notna() & (hist.iloc[d] >= need) & vol.iloc[d].gt(0) & opens.iloc[e].notna() & opens.iloc[x].notna()
        if L:
            past = closes.iloc[d - L] if d - L >= 0 else pd.Series(np.nan, index=closes.columns)
            sig = np.sign(c_now / past - 1)
            ok &= past.notna() & (sig != 0)
        else:
            sig = pd.Series(1.0, index=closes.columns)
        if long_only:
            sig = sig.abs()
        w = (sig * (TARGET / vol.iloc[d]).clip(upper=CAP)).where(ok, 0.0)
        n = int(ok.sum())
        if n == 0:
            prev = w
            continue
        r = opens.iloc[x] / opens.iloc[e] - 1
        bad = ((gap.iloc[e + 1:x + 1] < GAP_LO) | (gap.iloc[e + 1:x + 1] > GAP_HI)).any()   # corporate-action gap
        r = r.where(~bad, 0.0)
        live = ok & ~bad
        gross = float((w * r).where(live, 0.0).sum() / n)
        turn = float((w.where(live, prev) - prev).abs().sum() / n)
        roll = float(w.where(live, 0.0).abs().sum() / n) if expiry_in(cal, e, x + 1) else 0.0
        net = gross - cost * turn - 2 * cost * roll
        longs = float((w.clip(lower=0) * r).where(live, 0.0).sum() / n)
        rows.append({"entry": cal[e].date(), "gross": gross, "net": net, "turn": turn, "n": n,
                     "long_part": longs, "short_part": gross - longs})
        prev = w.where(live, prev)
    return pd.DataFrame(rows)


def stats(df: pd.DataFrame, seed: int = 0) -> dict:
    x = df["net"].to_numpy()
    if len(x) < 10:
        return {"n": len(x)}
    from scipy.stats import t as student
    m, s = x.mean(), x.std(ddof=1)
    tt = m / (s / np.sqrt(len(x)))
    rng = np.random.default_rng(seed)
    blocks = [x[i:i + 4] for i in range(0, len(x), 4)]
    boots = [np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))]).mean() for _ in range(5000)]
    eq = np.cumprod(1 + x)
    dd = float(np.max(1 - eq / np.maximum.accumulate(eq)))
    return {"n": len(x), "mean": m, "vol": s, "sharpe": m / s * np.sqrt(52) if s > 0 else 0.0,
            "p": float(student.sf(tt, len(x) - 1)), "ci": (float(np.quantile(boots, .025)), float(np.quantile(boots, .975))),
            "maxdd": dd, "pos": float((x > 0).mean()), "turn": float(df["turn"].mean()), "total": float(eq[-1] - 1),
            "gross_mean": float(df["gross"].mean()), "long": float(df["long_part"].mean()),
            "short": float(df["short_part"].mean())}


def passes(s: dict) -> bool:
    return s.get("n", 0) >= 10 and s["mean"] > 0 and s["ci"][0] > 0 and s["p"] < P_MAX and s["sharpe"] >= SHARPE_MIN


def show(name: str, s: dict, verdict: bool | None = None) -> None:
    if s.get("n", 0) < 10:
        print(f"{name}: too few weeks ({s.get('n', 0)})")
        return
    print(f"{name:22s} weeks {s['n']:3d} net {s['mean'] * 100:+.3f}%/wk (gross {s['gross_mean'] * 100:+.3f}) "
          f"vol {s['vol'] * 100:.2f}% Sharpe {s['sharpe']:+.2f} p {s['p']:.4f} CI {s['ci'][0] * 100:+.3f}..{s['ci'][1] * 100:+.3f}% "
          f"maxDD {s['maxdd'] * 100:.1f}% up-weeks {s['pos'] * 100:.0f}% turnover {s['turn']:.2f} total {s['total'] * 100:+.1f}% "
          f"| long {s['long'] * 100:+.3f} short {s['short'] * 100:+.3f}"
          + ("" if verdict is None else ("  PASS" if verdict else "  FAIL")), flush=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--stage", choices=list(STAGES), required=True)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    if x.stage != "train" and not x.configs:
        sys.exit("later stages run only the configs that passed the stage before: pass --configs")
    if x.stage == "final" and not x.i_accept_one_shot:
        sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
    opens, closes, nifty_open = load(x.folder)
    a, b = STAGES[x.stage]
    sel = lambda df: df[(df["entry"] >= a) & (df["entry"] <= b)]
    print(f"stage {x.stage} {a}..{b} · {closes.shape[1]} stocks · cost {COST * 1e4:.0f} bp/side (stress {STRESS * 1e4:.0f})")
    for name in (x.configs or list(CONFIGS)):
        L = CONFIGS[name]
        s = stats(sel(backtest(opens, closes, L, COST)))
        show(name, s, passes(s))
        show(f"  {name} @ stress", stats(sel(backtest(opens, closes, L, STRESS))))
    show("bench: equal-risk long", stats(sel(backtest(opens, closes, None, COST, long_only=True))))
    cal = closes.index
    nb = [{"entry": cal[e].date(), "gross": nifty_open.iloc[xx] / nifty_open.iloc[e] - 1, "turn": 0.0,
           "long_part": 0.0, "short_part": 0.0} for _, e, xx in weeks(cal)]
    nb = pd.DataFrame(nb)
    nb["net"] = nb["gross"]
    show("bench: NIFTY buy&hold", stats(sel(nb)))


if __name__ == "__main__":
    main()
