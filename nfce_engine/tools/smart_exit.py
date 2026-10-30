"""SMART-EXIT-1: early profit booking and smarter loss handling on the stock 3m signals
(../evidence/smart_exit_1_protocol.md).

  python tools/smart_exit.py <hist3m folder> --stage train [--cache rows_smart.pkl]
  python tools/smart_exit.py <hist3m folder> --stage validation --configs S1 ...   (only configs that passed)
"""
from __future__ import annotations

import argparse
import pickle
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import scanner_research as sr  # noqa: E402
from tools import stock3m_research as s3  # noqa: E402

P_MAX = 0.05 / 5
FAMILY = ("S1", "S2", "S3", "S4", "S5")


def walk_smart(d, j0: int, side: int, entry: float, R0: float, mode: str, exit_hm: int = s3.EOD):
    """One walk per mode; returns (exit price, reason, R0). A partial-exit mode returns the size-weighted average price.
    The reason carries the best favourable excursion in R0 ("stop|mfe=0.62") for the descriptive report.
    Convention (profit_lock.walk_lock): stop before any profit exit within a bar; gaps fill at the open; a moved
    level applies from the next bar."""
    o, h, l, c, m = (d[k].to_numpy() for k in ("open", "high", "low", "close", "hm"))
    fav = (lambda j: h[j] - entry) if side > 0 else (lambda j: entry - l[j])
    adv = (lambda j: entry - l[j]) if side > 0 else (lambda j: h[j] - entry)
    lvl = lambda k: entry + side * k * R0  # noqa: E731
    stop = None if mode == "S5" else lvl(-1.0)
    book = {"K1": 1.0, "S1": 0.5, "S2": 0.3, "S3": 3.0, "S4": 0.5, "S5": 0.5}.get(mode)
    best, was_below, t0 = 0.0, False, m[j0]
    done, parts = 0.0, []                            # LIVE: (weight, price) of the partial exits so far
    targets = [(1.0, 0.4), (2.0, 0.3), (3.0, 0.3)] if mode == "LIVE" else []

    def out(px, why, j):
        if parts:
            px = sum(w * p for w, p in parts) + (1 - done) * px
        return float(px), f"{why}|mfe={max(best, fav(j)) / R0:.2f}", R0

    for j in range(j0, len(d)):
        if stop is not None and ((side > 0 and l[j] <= stop) or (side < 0 and h[j] >= stop)):
            px = stop if j == j0 else (min(o[j], stop) if side > 0 else max(o[j], stop))
            return out(px, "stop" if (side * (stop - entry)) < 0 else "lock", j)
        if mode == "LIVE":
            while targets and fav(j) >= targets[0][0] * R0:
                k, w = targets.pop(0)
                parts.append((w, lvl(k)))
                done += w
                if k == 1.0:
                    stop = entry                              # breakeven after T1
            if not targets:
                return out(lvl(3.0), "target", j)
        elif fav(j) >= book * R0 and not (mode == "S5" and was_below):
            return out(lvl(book), "book", j)
        if mode == "S5":
            if was_below and fav(j) >= 0:                    # below -1R on an earlier bar, back at entry now
                return out(entry, "recover", j)
            if adv(j) >= R0:
                was_below = True
        if m[j] >= exit_hm:
            return out(c[j], "eod", j)
        best = max(best, fav(j))
        if mode == "S3" and best >= 0.5 * R0:
            new = entry + side * 0.5 * best
            if (side > 0 and new > stop) or (side < 0 and new < stop):
                stop = new
        if mode == "S4" and (m[j] - t0) >= 30 and side * (c[j] - entry) > 0:
            return out(c[j], "time_book", j)
    return out(c[-1], "eod_incomplete", len(d) - 1)


WALKERS = {name: (lambda n: lambda d, j0, s, e, r: walk_smart(d, j0, s, e, r, n))(name)
           for name in ("K1", "LIVE") + FAMILY}


def mfe_report(rows: list) -> str:
    def share(sel, k):
        return sum(float(r["reason"].split("mfe=")[1]) >= k for r in sel) / max(len(sel), 1)
    losers = [r for r in rows if r["net_r"] <= 0]
    return (f"K1 trades {len(rows)}: reached +0.3R {share(rows, .3):.0%}, +0.5R {share(rows, .5):.0%}, "
            f"+1R {share(rows, 1):.0%} | K1 losers {len(losers)}: had been at +0.3R {share(losers, .3):.0%}, "
            f"+0.5R {share(losers, .5):.0%} before losing")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--stage", choices=list(s3.SPLITS), required=True)
    ap.add_argument("--configs", nargs="*")
    ap.add_argument("--cache", type=Path)
    ap.add_argument("--i-accept-one-shot", action="store_true")
    x = ap.parse_args()
    if x.stage != "train" and not x.configs:
        sys.exit("later stages run only the configs that passed the stage before: pass --configs")
    if x.stage == "final" and not x.i_accept_one_shot:
        sys.exit("the final stage is one-shot: pass --i-accept-one-shot")
    if x.cache and x.cache.exists():
        rows = pickle.loads(x.cache.read_bytes())
    else:
        rows = s3.trades(x.folder, mults=(), walkers=WALKERS)
        if x.cache:
            x.cache.write_bytes(pickle.dumps(rows))
    a, b = s3.SPLITS[x.stage]
    print(f"stage {x.stage} ({a}..{b}); Bonferroni p < {P_MAX:.3f}")
    print(mfe_report([r for r in rows["K1"] if a <= r["day"] <= b]))
    for name in ["K1", "LIVE"] + (x.configs or list(FAMILY)):
        sel = [r for r in rows[name] if a <= r["day"] <= b]
        s = sr.stats(sel)
        win = [r["net_r"] for r in sel if r["net_r"] > 0]
        loss = [r["net_r"] for r in sel if r["net_r"] <= 0]
        reasons, days = {}, {}
        for r in sel:
            k = r["reason"].split("|")[0]
            reasons[k] = reasons.get(k, 0) + 1
            days[r["day"]] = days.get(r["day"], 0.0) + r["net_r"]
        ok = s["n"] and s["net_r"] > 0 and s["ci"][0] > 0 and s["p_day"] < P_MAX
        print(f"{name:4s} n={s['n']} win {s['win'] * 100:.1f}% gross {s['gross_r']:+.3f} net {s['net_r']:+.3f}R "
              f"CI {s['ci'][0]:+.3f}..{s['ci'][1]:+.3f} p {s['p_day']:.4f} PF {s['pf']:.2f} Rs {s['net_inr']:+,.0f} "
              f"avg win {sum(win) / max(len(win), 1):+.3f} avg loss {sum(loss) / max(len(loss), 1):+.3f} "
              f"worst trade {min(r['net_r'] for r in sel):+.2f}R worst day {min(days.values()):+.1f}R exits {reasons}"
              + ("" if name in ("K1", "LIVE") else ("  PASS" if ok else "  FAIL")), flush=True)


if __name__ == "__main__":
    main()
