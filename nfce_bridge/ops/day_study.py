"""22 Oct after-close study: loss post-mortem (MAE/MFE, recovery after the stop), groupings, the 1 Cr view,
and the registered live variants V0-V4 (../evidence/live_variants_protocol.md).
usage (from nfce_bridge/): PYTHONPATH=. .venv/bin/python day_study.py
"""
import collections, json, sqlite3, statistics as st
from datetime import date, datetime, timedelta
from pathlib import Path

import pandas as pd
from bridge.costs import futures_cost_points

DB, ONE = "data/nfce.db", Path("data/study_1m")
REC = sqlite3.connect("data/study_quotes_20261022.db")
LOT = {}
for r in json.load(open("data/instruments_NSE.json"))["rows"]:
    if r["instrument_type"] == "FUT":
        LOT.setdefault(r["underlying_symbol"], r["lot_size"])
LOT.setdefault("SENSEX", 20)

def bars(day, sym):
    f = ONE / day / f"{sym}__fut.csv"
    d = pd.read_csv(f, parse_dates=["ts"]).set_index("ts")
    return d[d.index.map(lambda t: t.hour * 60 + t.minute < 15 * 60 + 15)]

SPREAD = {}
def half_spread(sym, px):
    if sym not in SPREAD:
        v = [a - b for b, a in REC.execute("select bid, ask from q where symbol like ? and bid>0 and ask>0",
                                            (f"NSE_FO:{sym}26OCTFUT",))]
        SPREAD[sym] = st.median(v) / 2 if v else None
    return SPREAD[sym] if SPREAD[sym] is not None else 0.00025 * px

con = sqlite3.connect(DB)
T = [dict(zip([c[0] for c in con.execute("select * from paper_trades limit 0").description], r))
     for r in con.execute("select * from paper_trades where opened>='2026-10-21' and book in ('stock3m','scanner','executable')")]

# ---------- 1. post-mortem ----------
rows = []
for t in T:
    day = t["opened"][:10]
    try:
        b = bars(day, t["underlying"])
    except FileNotFoundError:
        print("no bars", t["underlying"]); continue
    op = pd.Timestamp(t["opened"]).floor("min")
    b = b[b.index > op]
    s, e, sl, t1 = t["side"], t["entry"], t["sl"], t["t1"]
    R = abs(e - sl)
    adv = lambda row: (row.high - e) / R if s < 0 else (e - row.low) / R
    fav = lambda row: (e - row.low) / R if s < 0 else (row.high - e) / R
    first, mae, k_stop = None, 0.0, None
    for i, (ts, row) in enumerate(b.iterrows()):
        if adv(row) >= 1:
            first, k_stop = "stop", i; break
        if fav(row) >= 1:
            first = "t1"; break
        mae = max(mae, adv(row))
    after = b.iloc[k_stop + 1:] if k_stop is not None else b.iloc[0:0]
    rec_t1 = bool(len(after)) and max(fav(r) for _, r in after.iterrows()) >= 1
    rec_t2 = bool(len(after)) and max(fav(r) for _, r in after.iterrows()) >= 2
    mfe = max((fav(r) for _, r in b.iterrows()), default=0)
    close_r = s * (b.close.iloc[-1] - e) / R if len(b) else 0
    rows.append(dict(day=day, book=t["book"], sym=t["underlying"], side=s, hour=int(t["opened"][11:13]),
                     opened=t["opened"][11:16], R_pct=R / e * 100, net_r=(t["net_pts"] or 0) / R, exit=t["exit_reason"],
                     first=first, mins_to_stop=k_stop + 1 if k_stop is not None else None, mfe=mfe,
                     rec_t1=rec_t1, rec_t2=rec_t2, close_r=close_r, net_inr=(t["net_pts"] or 0) * LOT.get(t["underlying"], 1)))
df = pd.DataFrame(rows)
df.to_csv("day_trades.csv", index=False)

def g(d, by):
    x = d.groupby(by).agg(n=("net_r", "size"), win=("net_r", lambda v: (v > 0).mean()), net_r=("net_r", "mean"),
                          inr=("net_inr", "sum"), stop_pct=("first", lambda v: (v == "stop").mean()),
                          rec_t1=("rec_t1", "mean"), close_r=("close_r", "mean"), R_pct=("R_pct", "median"))
    return x.round(2).to_string()

pd.set_option("display.width", 200)
print("== by day/book\n", g(df, ["day", "book"]))
print("== by day/book/side\n", g(df, ["day", "book", "side"]))
print("== by hour (all books)\n", g(df, ["hour"]))
s3 = df[df.book.isin(["stock3m", "executable"])]
stopped = s3[s3["first"] == "stop"]
print(f"== stock3m+index stopped first: {len(stopped)} of {len(s3)}; median minutes to stop "
      f"{stopped.mins_to_stop.median():.0f}; within 5 min {(stopped.mins_to_stop <= 5).mean():.0%}; "
      f"later reached T1 {stopped.rec_t1.mean():.0%}, T2 {stopped.rec_t2.mean():.0%}; "
      f"median MFE of all {s3.mfe.median():.2f}R; held to 15:15 would give mean {s3.close_r.mean():+.2f}R")
print("== median stop distance % of price, stock3m:", round(df[df.book == "stock3m"].R_pct.median(), 3))
# clusters: >=4 same-side stock3m/index trades within 6 minutes
cl = []
for (day, side), d in s3.groupby(["day", "side"]):
    times = sorted(d.opened)
    for i, a in enumerate(times):
        win = [x for x in times if a <= x <= (datetime.strptime(a, "%H:%M") + timedelta(minutes=6)).strftime("%H:%M")]
        if len(win) >= 4:
            cl.append((day, side, a, len(win)))
print("== clusters (>=4 same side within 6 min):", sorted(set(cl))[:10])

# ---------- 2. the 1 Cr view: every signal of both days at 1% risk (Rs 1,00,000), net of costs ----------
for day, d in df.groupby("day"):
    print(f"== 1 Cr view {day}: {len(d)} signals, total {d.net_r.sum():+.1f}R = Rs {d.net_r.sum() * 100000:+,.0f}; "
          f"by book " + ", ".join(f"{b} {x.net_r.sum():+.1f}R" for b, x in d.groupby("book")))

# ---------- 3. live variants V0-V4 on signals after 13:45 on 22 Oct ----------
def sim(b, side, fill, sl, t1, t_stop_min=None):
    """One lot, all out at T1, stop first in the same bar, 15:15 square-off. Returns (exit price, reason)."""
    for i, (ts, row) in enumerate(b.iterrows()):
        if (side < 0 and row.high >= sl) or (side > 0 and row.low <= sl):
            return sl, "stop"
        if (side < 0 and row.low <= t1) or (side > 0 and row.high >= t1):
            return t1, "T1"
        if t_stop_min is not None and i + 1 >= t_stop_min:
            return row.close, "time"
    return (b.close.iloc[-1], "15:15") if len(b) else (fill, "none")

reg = [t for t in T if t["book"] in ("stock3m", "executable") and t["opened"] >= "2026-10-22T13:45"]
reg.sort(key=lambda t: (t["opened"], t["underlying"]))
res = collections.defaultdict(list)
taken = []
for t in reg:
    sym, s, e, sl = t["underlying"], t["side"], t["entry"], t["sl"]
    R = abs(e - sl)
    b = bars("2026-10-22", sym)
    b = b[b.index > pd.Timestamp(t["opened"]).floor("min")]
    if not len(b):
        continue
    fill0 = b.open.iloc[0]
    lot, hs = LOT.get(sym, 1), half_spread(sym, e)
    def book(v, fill, x, R_v):
        c = futures_cost_points(fill, x[0], s, date(2026, 10, 22), lot, 1, 2, hs)
        res[v].append(((s * (x[0] - fill) - c) / R_v, (s * (x[0] - fill) - c) * lot, x[1], sym))
    book("V0", fill0, sim(b, s, fill0, e - s * R, e + s * R), R)
    book("V1", fill0, sim(b, s, fill0, e - s * 2 * R, e + s * 2 * R), 2 * R)
    conf = e + s * 0.5 * R
    w = b.iloc[:15]
    hit = [i for i, (_, r) in enumerate(w.iterrows()) if (s > 0 and r.high >= conf) or (s < 0 and r.low <= conf)]
    if hit:
        book("V2", conf, sim(b.iloc[hit[0] + 1:], s, conf, e - s * R, e + s * R), 1.5 * R)
    else:
        res["V2"].append((None, 0, "skipped", sym))
    recent = [x for x in taken if x[1] == s and pd.Timestamp(t["opened"]) - timedelta(minutes=30) < x[0] <= pd.Timestamp(t["opened"])]
    if len(recent) < 2:
        taken.append((pd.Timestamp(t["opened"]), s))
        book("V3", fill0, sim(b, s, fill0, e - s * R, e + s * R), R)
    else:
        res["V3"].append((None, 0, "skipped", sym))
    book("V4", fill0, sim(b, s, fill0, e - s * R, e + s * R, t_stop_min=30), R)
print(f"== live variants: {len(reg)} qualifying signals after 13:45")
for v in ["V0", "V1", "V2", "V3", "V4"]:
    xs = [x for x in res[v] if x[0] is not None]
    sk = len(res[v]) - len(xs)
    if xs:
        print(f"{v}: n={len(xs)} skipped {sk} wins {sum(x[0] > 0 for x in xs)} mean {st.mean(x[0] for x in xs):+.3f}R "
              f"total Rs {sum(x[1] for x in xs):+,.0f} | " + ", ".join(f"{x[3]} {x[0]:+.2f}R {x[2]}" for x in xs))
    else:
        print(f"{v}: n=0 skipped {sk}")
