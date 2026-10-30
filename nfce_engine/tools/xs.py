"""Cross-sectional momentum (XM), short-term reversal (XR) and NIFTY overnight (ON) (../evidence/xs_protocol.md).

  python tools/xs.py <daily folder> --stage train
  python tools/xs.py <daily folder> --stage validation --configs XM ...    (only configs that passed train)
  python tools/xs.py <daily folder> --stage final --configs ... --i-accept-one-shot

No look-ahead: ranks and volatility use closes up to the decision day; trades happen at the next open and are held
to the open after the next decision. Market-neutral: half the gross exposure long, half short.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.tsmom import GAP_HI, GAP_LO, STAGES, VOL_N, expiry_in, load, weeks  # noqa: E402

COST, STRESS, IDX_COST = 0.0008, 0.0012, 0.0004
FRAC, P_MAX, SHARPE_MIN = 0.20, 0.05 / 3, 0.5


def months(cal: pd.DatetimeIndex) -> list[tuple[int, int, int]]:
    ym = pd.Series(cal.year * 100 + cal.month, index=range(len(cal)))
    dec = [g.index[-1] for _, g in ym.groupby(ym.values, sort=False)]
    return [(a, a + 1, b + 1) for a, b in zip(dec, dec[1:]) if b + 1 < len(cal)]


def cross_section(opens, closes, periods, score_fn, need: int, long_low: bool, cost: float) -> pd.DataFrame:
    cal = closes.index
    vol = closes.pct_change(fill_method=None).rolling(VOL_N, min_periods=VOL_N).std()
    hist = closes.notna().cumsum()
    gap = opens / closes.shift(1) - 1
    rows, prev = [], pd.Series(0.0, index=closes.columns)
    for d, e, x in periods:
        sc = score_fn(closes, d)
        ok = sc.notna() & (hist.iloc[d] >= need) & vol.iloc[d].gt(0) & opens.iloc[e].notna() & opens.iloc[x].notna()
        n = int(ok.sum())
        k = int(np.floor(FRAC * n))
        if k < 3:
            continue
        ranked = sc[ok].sort_values()
        low, high = ranked.index[:k], ranked.index[-k:]
        longs, shorts = (low, high) if long_low else (high, low)
        inv = 1 / vol.iloc[d]
        w = pd.Series(0.0, index=closes.columns)
        w[longs] = 0.5 * inv[longs] / inv[longs].sum()
        w[shorts] = -0.5 * inv[shorts] / inv[shorts].sum()
        r = opens.iloc[x] / opens.iloc[e] - 1
        bad = ((gap.iloc[e + 1:x + 1] < GAP_LO) | (gap.iloc[e + 1:x + 1] > GAP_HI)).any()
        r = r.where(~bad, 0.0).fillna(0.0)
        gross = float((w * r).sum())
        turn = float((w - prev).abs().sum())
        roll = float(w.abs().sum()) if expiry_in(cal, e, x + 1) else 0.0
        rows.append({"entry": cal[e].date(), "gross": gross, "net": gross - cost * turn - 2 * cost * roll,
                     "turn": turn, "long_part": float((w.clip(lower=0) * r).sum()),
                     "short_part": float((w.clip(upper=0) * r).sum())})
        prev = w
    return pd.DataFrame(rows)


def mom_score(closes, d):                                   # 12-1 momentum: t-252 .. t-21
    return closes.iloc[d - 21] / closes.iloc[d - 252] - 1 if d >= 252 else pd.Series(np.nan, index=closes.columns)


def rev_score(closes, d):                                   # past 5 trading days
    return closes.iloc[d] / closes.iloc[d - 5] - 1 if d >= 5 else pd.Series(np.nan, index=closes.columns)


def overnight(nifty_close: pd.Series, nifty_open: pd.Series) -> pd.DataFrame:
    r = (nifty_open / nifty_close.shift(1) - 1).dropna()
    return pd.DataFrame({"entry": [t.date() for t in r.index], "gross": r.to_numpy(),
                         "net": r.to_numpy() - 2 * IDX_COST, "turn": 2.0, "long_part": r.to_numpy(), "short_part": 0.0})


def stats(df: pd.DataFrame, block: int, per_year: int, seed: int = 0) -> dict:
    x = df["net"].to_numpy()
    if len(x) < 10:
        return {"n": len(x)}
    from scipy.stats import t as student
    m, s = x.mean(), x.std(ddof=1)
    rng = np.random.default_rng(seed)
    blocks = [x[i:i + block] for i in range(0, len(x), block)]
    boots = [np.concatenate([blocks[j] for j in rng.integers(0, len(blocks), len(blocks))]).mean() for _ in range(5000)]
    eq = np.cumprod(1 + x)
    return {"n": len(x), "mean": m, "sharpe": m / s * np.sqrt(per_year) if s > 0 else 0.0,
            "p": float(student.sf(m / (s / np.sqrt(len(x))), len(x) - 1)),
            "ci": (float(np.quantile(boots, .025)), float(np.quantile(boots, .975))),
            "maxdd": float(np.max(1 - eq / np.maximum.accumulate(eq))), "total": float(eq[-1] - 1),
            "gross": float(df["gross"].mean()), "long": float(df["long_part"].mean()),
            "short": float(df["short_part"].mean()), "turn": float(df["turn"].mean())}


def show(name, s, market=None, verdict=None):
    if s.get("n", 0) < 10:
        print(f"{name}: too few periods ({s.get('n', 0)})")
        return
    corr = f" corr(NIFTY) {market:+.2f}" if market is not None else ""
    print(f"{name:16s} periods {s['n']:4d} net {s['mean'] * 100:+.3f}% (gross {s['gross'] * 100:+.3f}) Sharpe "
          f"{s['sharpe']:+.2f} p {s['p']:.4f} CI {s['ci'][0] * 100:+.3f}..{s['ci'][1] * 100:+.3f}% maxDD "
          f"{s['maxdd'] * 100:.1f}% total {s['total'] * 100:+.1f}% | long {s['long'] * 100:+.3f} short "
          f"{s['short'] * 100:+.3f} turnover {s['turn']:.2f}{corr}" + ("" if verdict is None else
                                                                       ("  PASS" if verdict else "  FAIL")), flush=True)


def passes(s):
    return s.get("n", 0) >= 10 and s["mean"] > 0 and s["ci"][0] > 0 and s["p"] < P_MAX and s["sharpe"] >= SHARPE_MIN


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
    nifty = pd.read_pickle(x.folder / "NIFTY_1d.pkl")
    cal = closes.index
    a, b = STAGES[x.stage]
    sel = lambda df: df[(df["entry"] >= a) & (df["entry"] <= b)].reset_index(drop=True)
    wanted = x.configs or ["XM", "XR", "ON"]
    print(f"stage {x.stage} {a}..{b} · {closes.shape[1]} stocks · Bonferroni p < {P_MAX:.4f}")
    defs = {"XM": (months(cal), mom_score, 260, False, 3, 12), "XR": (weeks(cal), rev_score, 65, True, 4, 52)}
    for name in ("XM", "XR"):
        if name not in wanted:
            continue
        per, fn, need, low, block, py = defs[name]
        for label, c in ((name, COST), (f"  {name} @ 12bp", STRESS)):
            df = sel(cross_section(opens, closes, per, fn, need, low, c))
            nb = pd.Series([nifty_open.iloc[xx] / nifty_open.iloc[e] - 1 for _, e, xx in per],
                           index=[cal[e].date() for _, e, xx in per])
            corr = float(np.corrcoef(df["gross"], nb.reindex(df["entry"]).to_numpy())[0, 1]) if len(df) > 2 else None
            s = stats(df, block, py)
            show(label, s, corr, passes(s) if c == COST else None)
    if "ON" in wanted:
        s = stats(sel(overnight(nifty["close"], nifty["open"])), 20, 250)
        show("ON", s, None, passes(s))


if __name__ == "__main__":
    main()
