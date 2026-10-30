"""News brief + news watchlist for F&O stocks (owner, 26 Oct 2026: "see the complete extensive news in morning and then
track that later for only those which will have any news or orders").

  brief  : every NSE announcement for F&O stocks since the previous session's close (15:30), sorted into RESULTS
           (with the quarter's numbers from the XBRL filing: revenue, profit, EPS, vs the same quarter a year ago),
           ORDERS (contracts, agreements) and MAJOR (acquisitions, management, ratings, regulatory actions, ...);
           routine filings (newspaper copies, analyst-meet notices, ESOPs, ...) are dropped. Writes
           data/news/brief_<day>.md and data/news/watch_<day>.json (the watchlist).
  track  : every N minutes until END, the watchlist's live move (vs previous close, vs open) from Upstox quotes,
           saved to data/news/track_<day>.db; F&O news logged by ops/news_watch.py during the day joins the list.

Read-only: NSE public pages and Upstox market quotes. No trades, no messages.
usage (from nfce_bridge/): .venv/bin/python ops/news_brief.py brief [YYYY-MM-DD]
                           .venv/bin/python ops/news_brief.py track [END HH:MM] [every_min]
"""
import datetime as dt, json, re, sqlite3, sys, time
from pathlib import Path
import httpx

H = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/126.0 Safari/537.36",
     "Accept": "application/json, text/plain, */*", "Accept-Language": "en-US,en;q=0.9"}
NSE = "https://www.nseindia.com"
OUT = Path("data/news")
SKIP = ("newspaper", "analysts/institutional", "investor presentation", "esop", "esos", "record date", "trading window",
        "certificate", "shareholders meeting", "loss of share", "duplicate", "copy of", "esps", "reg. 74", "74(5)",
        "closure of trading", "spurts in volume", "clarification - financial results")
ORDER = ("order", "contract", "agreement", "loi", "letter of intent", "award", "bagging", "tender")
MAJOR_DESC = ("acquisition", "amalgamation", "merger", "scheme of arrangement", "change in management", "resignation",
              "change in director", "change in auditor", "credit rating", "action(s) taken", "insolvency", "buyback",
              "buy back", "fund raising", "preferential", "qip", "bonus", "split", "dividend", "joint venture",
              "disinvestment", "restructuring", "fraud", "default", "litigation", "dispute", "search", "penalty")
MAJOR_TEXT = ("usfda", "fda", "warning letter", "import alert", "plant", "fire", "strike", "shutdown", "approval",
              "acquire", "stake", "merger", "demerger", "raid", "search", "penalty", "fraud", "default", "resign",
              "ceo", "md ", "guidance", "launch", "capacity", "expansion", "sebi", "rbi", "court", "tribunal", "nclt")


def nse() -> httpx.Client:
    c = httpx.Client(headers=H, timeout=60, follow_redirects=True)
    c.get(f"{NSE}/companies-listing/corporate-filings-announcements")
    return c


def fno_symbols() -> set[str]:
    rows = json.load(open("data/instruments_NSE.json"))["rows"]
    return {r["underlying_symbol"] for r in rows if r.get("instrument_type") == "FUT" and r.get("underlying_type") == "EQUITY"}


def prev_session(day: dt.date) -> dt.date:
    d = day - dt.timedelta(days=1)
    while d.weekday() >= 5:
        d -= dt.timedelta(days=1)
    return d


def ts(s: str | None) -> dt.datetime | None:
    for f in ("%d-%b-%Y %H:%M:%S", "%d-%b-%Y %H:%M"):
        try:
            return dt.datetime.strptime(s or "", f)
        except ValueError:
            pass
    return None


def classify(desc: str, text: str) -> str | None:
    d, t = (desc or "").lower(), (text or "").lower()
    if any(k in d for k in SKIP):
        return None
    if "financial result" in d or ("outcome of board meeting" in d and "result" in t):
        return "RESULTS"
    if "bagging" in d or ("contract" in d or "agreement" in d) and any(k in t for k in ORDER):
        return "ORDERS"
    if any(k in d for k in MAJOR_DESC):                         # before the text check: "orders passed" is regulatory
        return "MAJOR"
    if any(k in t for k in ORDER):
        return "ORDERS"
    if any(k in t for k in MAJOR_TEXT):
        return "MAJOR"
    return None


def announcements(c: httpx.Client, since: dt.datetime, until: dt.datetime) -> list[dict]:
    out, d = [], since.date()
    while d <= until.date():
        r = c.get(f"{NSE}/api/corporate-announcements", params={"index": "equities", "from_date": f"{d:%d-%m-%Y}",
                                                                   "to_date": f"{d:%d-%m-%Y}"})
        out += r.json() if r.status_code == 200 else []
        d += dt.timedelta(days=1)
        time.sleep(1)
    return [x for x in out if (t := ts(x.get("an_dt"))) and since <= t <= until]


def xbrl_numbers(c: httpx.Client, url: str) -> dict:
    x = c.get(url).text
    ctx = {i: re.findall(r"<xbrli:(?:startDate|endDate)>([^<]+)<", body)
           for i, body in re.findall(r'<xbrli:context id="([^"]+)">(.*?)</xbrli:context>', x, re.S)}
    out = {}
    tags = {"revenue": ("RevenueFromOperations", "InterestEarned"),          # banks report interest earned
            "profit": ("ProfitLossForPeriod", "ProfitLossForThePeriod"),
            "eps": ("BasicEarningsLossPerShareFromContinuingOperations", "BasicEarningsPerShareAfterExtraordinaryItems")}
    for name, alts in tags.items():
        for tag in alts:
            vals = []
            for cref, val in re.findall(r"<[\w-]+:" + tag + r'\b[^>]*contextRef="([^"]+)"[^>]*>\s*([-\d.]+)\s*<', x):
                p = ctx.get(cref, [])
                if len(p) == 2:
                    vals.append(((dt.date.fromisoformat(p[1]) - dt.date.fromisoformat(p[0])).days, float(val)))
            if vals:
                q = [v for d, v in vals if 80 <= d <= 95]              # the quarter, not the year-to-date
                days, v = (90, q[0]) if q else min(vals)              # some filers give only the half year
                out[name], out["months"] = v, round(days / 30.4)
                break
    return out


def results(c: httpx.Client, sym: str) -> dict | None:
    r = c.get(f"{NSE}/api/integrated-filing-results", params={"index": "equities", "symbol": sym,
                                                               "type": "Integrated Filing- Financials", "period_ended": "all"})
    rows = (r.json() or {}).get("data", []) if r.status_code == 200 else []
    if not rows:
        return None
    by_q: dict[tuple, dict] = {}
    for x in rows:
        q = dt.datetime.strptime(x["qe_Date"].title(), "%d-%b-%Y").date()
        k = (q, x.get("consolidated"))
        if k not in by_q or (ts(x.get("broadcast_Date")) or dt.datetime.min) > (ts(by_q[k].get("broadcast_Date")) or dt.datetime.min):
            by_q[k] = x
    last_q = max(q for q, _ in by_q)
    kind = "Consolidated" if (last_q, "Consolidated") in by_q else next(k for q, k in by_q if q == last_q)
    cur = by_q[(last_q, kind)]
    yago = by_q.get((last_q.replace(year=last_q.year - 1), kind))
    now = xbrl_numbers(c, cur["xbrl"])
    old = xbrl_numbers(c, yago["xbrl"]) if yago else {}
    same = old.get("months") == now.get("months")
    yoy = {k: (now[k] / old[k] - 1) if same and old.get(k) and old[k] > 0 and k in now else None for k in ("revenue", "profit")}
    return {"quarter": last_q.isoformat(), "kind": kind, "filed": cur.get("broadcast_Date"), **now,
            "rev_yoy": yoy["revenue"], "pat_yoy": yoy["profit"], "profit_year_ago": old.get("profit")}


def cr(v):                                     # rupees -> crore
    return f"₹{v / 1e7:,.0f} cr" if v is not None else "n/a"


def pct(v):
    return f"{v * 100:+.0f}%" if v is not None else "n/a"


def brief(day: dt.date) -> None:
    fno = fno_symbols()
    since = dt.datetime.combine(prev_session(day), dt.time(15, 30))
    until = dt.datetime.combine(day, dt.time(23, 59))
    c = nse()
    items = [x for x in announcements(c, since, until) if x.get("symbol") in fno]
    watch: dict[str, dict] = {}
    for x in sorted(items, key=lambda x: ts(x["an_dt"])):
        cat = classify(x.get("desc", ""), x.get("attchmntText", ""))
        if not cat:
            continue
        w = watch.setdefault(x["symbol"], {"symbol": x["symbol"], "cats": [], "items": []})
        if cat not in w["cats"]:
            w["cats"].append(cat)
        w["items"].append({"time": x["an_dt"], "cat": cat, "desc": x.get("desc"), "text": (x.get("attchmntText") or "")[:240],
                           "file": x.get("attchmntFile")})
    cal = json.load(open("data/results_calendar_live.json")).get("rows", {}) if Path("data/results_calendar_live.json").exists() else {}
    window = {prev_session(day).isoformat(), day.isoformat()}
    for sym in sorted(fno):
        if set(cal.get(sym, [])) & window or "RESULTS" in watch.get(sym, {}).get("cats", []):
            try:
                res = results(c, sym)
            except Exception as e:
                res = {"error": repr(e)[:100]}
            time.sleep(0.5)
            if res and not res.get("error") and res["quarter"] >= (day - dt.timedelta(days=60)).isoformat():
                w = watch.setdefault(sym, {"symbol": sym, "cats": [], "items": []})
                if "RESULTS" not in w["cats"]:
                    w["cats"].insert(0, "RESULTS")
                w["results"] = res
            elif sym in cal and day.isoformat() in cal[sym]:
                w = watch.setdefault(sym, {"symbol": sym, "cats": [], "items": []})
                w.setdefault("pending", "results expected today (board meeting)")
                if "RESULTS DUE" not in w["cats"]:
                    w["cats"].append("RESULTS DUE")
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"watch_{day:%Y%m%d}.json").write_text(json.dumps(sorted(watch.values(), key=lambda w: w["symbol"]), indent=1))
    lines = [f"# F&O news brief, {day:%a %d %b %Y} (news since {since:%d %b %H:%M})", "",
             f"{len(watch)} F&O stocks with news. Watchlist: data/news/watch_{day:%Y%m%d}.json", ""]
    for cat, head in (("RESULTS", "## Results (quarter vs same quarter last year)"), ("ORDERS", "## Orders / contracts"),
                      ("MAJOR", "## Other major news")):
        lines.append(head)
        n = 0
        for w in sorted(watch.values(), key=lambda w: w["symbol"]):
            if cat not in w["cats"]:
                continue
            n += 1
            if cat == "RESULTS" and w.get("results"):
                r = w["results"]
                span = "Q" if r.get("months", 3) == 3 else f"{r.get('months')} months"
                lines.append(f"- **{w['symbol']}** {span} to {r['quarter']} ({r['kind']}, filed {r.get('filed')}): revenue "
                             f"{cr(r.get('revenue'))} ({pct(r.get('rev_yoy'))} YoY), profit {cr(r.get('profit'))} "
                             f"({pct(r.get('pat_yoy'))} YoY{'; loss a year ago' if (r.get('profit_year_ago') or 0) < 0 else ''})"
                             f", EPS {r.get('eps', 'n/a')}")
            else:
                for it in [i for i in w["items"] if i["cat"] == cat][:2]:
                    lines.append(f"- **{w['symbol']}** {it['time'][-8:-3]} {it['desc']}: {it['text'][:160]}")
        pend = [w["symbol"] for w in watch.values() if cat == "RESULTS" and w.get("pending") and not w.get("results")]
        if pend:
            lines.append(f"- Results expected today (not filed yet): {', '.join(sorted(pend))}")
            n += 1
        if not n:
            lines.append("- none")
        lines.append("")
    lines.append("_Source: NSE corporate announcements and integrated filings (XBRL). Numbers as filed; not advice._")
    text = "\n".join(lines)
    (OUT / f"brief_{day:%Y%m%d}.md").write_text(text)
    print(text)


def track(end: str, every: int) -> None:
    from bridge.config import Settings
    day = dt.date.today()
    tok = json.load(open(Settings.from_env().token_file))
    tok = tok.get("access_token", tok) if isinstance(tok, dict) else tok
    UH = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
    rows = json.load(open("data/instruments_NSE.json"))["rows"]
    eq = {r["underlying_symbol"]: r["underlying_key"] for r in rows
          if r.get("instrument_type") == "FUT" and r.get("underlying_type") == "EQUITY"}
    db = sqlite3.connect(OUT / f"track_{day:%Y%m%d}.db")
    db.execute("create table if not exists t (ts text, symbol text, cats text, last real, prev_close real, open real, "
               "high real, low real, volume real, chg real, from_open real)")
    while dt.datetime.now().strftime("%H:%M") < end:
        watch = {w["symbol"]: ",".join(w["cats"]) for w in json.loads((OUT / f"watch_{day:%Y%m%d}.json").read_text())}
        news_db = Path(f"data/study_news_{day:%Y%m%d}.db")
        if news_db.exists():                                  # F&O news that came out during the day joins the list
            for sym, desc, text in sqlite3.connect(news_db).execute("select symbol, category, text from news where fno=1"):
                cat = classify(desc, text)
                if cat and sym not in watch:
                    watch[sym] = cat + " (intraday)"
        keys = {eq[s]: s for s in watch if s in eq}
        now = dt.datetime.now().isoformat(timespec="seconds")
        try:
            data = httpx.get("https://api.upstox.com/v2/market-quote/quotes", headers=UH, timeout=30,
                             params={"instrument_key": ",".join(keys)}).json().get("data", {})
        except Exception as e:
            print(now, "quote fail", repr(e)[:100], flush=True); time.sleep(60); continue
        out = []
        for q in data.values():
            sym = keys.get(q.get("instrument_token")) or q.get("symbol")
            o, last = q.get("ohlc") or {}, q.get("last_price")
            prev = (last - q["net_change"]) if last is not None and q.get("net_change") is not None else None
            chg = last / prev - 1 if prev else None
            fo = last / o["open"] - 1 if o.get("open") else None
            out.append((now, sym, watch.get(sym, ""), last, prev, o.get("open"), o.get("high"), o.get("low"),
                        q.get("volume"), chg, fo))
        with db:
            db.executemany("insert into t values (?,?,?,?,?,?,?,?,?,?,?)", out)
        print(now[11:16], " | ".join(f"{s} {c * 100:+.1f}%" for _, s, _, _, _, _, _, _, _, c, _ in
                                     sorted(out, key=lambda r: -abs(r[9] or 0))[:12] if c is not None), flush=True)
        time.sleep(every * 60)


if __name__ == "__main__":
    if sys.argv[1] == "brief":
        brief(dt.date.fromisoformat(sys.argv[2]) if len(sys.argv) > 2 else dt.date.today())
    else:
        track(sys.argv[2] if len(sys.argv) > 2 else "15:30", int(sys.argv[3]) if len(sys.argv) > 3 else 5)
