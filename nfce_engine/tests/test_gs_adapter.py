"""nfce_bridge/bridge/gs_adapter.py: live = replay parity, fail-closed isolation, persistence, and that only the GS
glue (bridge/gs_live.py) imports it. The module is loaded from its file, so the bridge package is never imported."""
import ast
import importlib.util
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import alpha_sip as sip  # noqa: E402
from gs import calendar as cal  # noqa: E402
from gs import execution as ex  # noqa: E402
from gs import features as ft  # noqa: E402
from gs import store as gstore  # noqa: E402

BRIDGE = Path(__file__).resolve().parents[2] / "nfce_bridge"
ADAPTER = BRIDGE / "bridge" / "gs_adapter.py"
DAY = date(2026, 10, 27)


def load():
    spec = importlib.util.spec_from_file_location("gs_adapter_under_test", ADAPTER)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def at(hh, mm, ss=0):
    return datetime(2026, 10, 27, hh, mm, ss, tzinfo=cal.IST)


def universe():
    hist, x = [], DAY
    for _ in range(30):
        x = cal.prev_session(x)
        hist.append(ft.DailyBar(x, 1000, 1010, 990, 1000))
    win, x = [], DAY
    for _ in range(14):
        x = cal.prev_session(x)
        win.append((x, 500.0))
    return {"S0": sip.StockDay("S0", sorted(hist, key=lambda b: b.day), win)}


def events():
    def bar(hh, mm, o, h, l, c, v):
        s = at(hh, mm)
        return ft.Bar("S0", s, 3, o, h, l, c, v, s + timedelta(minutes=3, seconds=1))
    bars = [bar(9, 15, 1000, 1004, 999, 1003, 500), bar(9, 18, 1003, 1006, 1002, 1005, 500),
            bar(9, 30, 1005, 1008, 1004, 1007, 300)]
    books = [ex.Book(at(9, 30 + i), ((1005.0, 5000),), ((1005.5, 5000),), 1005, 100_000 * (i + 1)) for i in range(3)]
    books += [ex.Book(at(9, 33, 2), ((1006.9, 5000),), ((1007.1, 5000),), 1007, 400_000),
              ex.Book(at(9, 33, 5), ((1007.0, 5000),), ((1007.2, 5000),), 1007, 410_000),
              ex.Book(at(9, 34), ((1005.5, 20000),), ((1005.9, 20000),), 1005.8, 500_000),
              ex.Book(at(15, 15, 1), ((1015.0, 5000),), ((1015.5, 5000),), 1015, 900_000)]
    evs = [(b.available_at, 0, "bar", b) for b in bars] + [(b.ts, 1, "book", b) for b in books]
    return sorted(evs, key=lambda e: (e[0], e[1]))


def feed_adapter(ad):
    for _, _, kind, o in events():
        if kind == "bar":
            ad.on_bar("S0", o.start, o.minutes, o.open, o.high, o.low, o.close, o.volume, o.available_at)
        else:
            ad.on_quote("S0", {"buy": [{"price": p, "quantity": q} for p, q in o.bids],
                               "sell": [{"price": p, "quantity": q} for p, q in o.asks]}, o.last, o.volume, o.ts)
    ad.on_clock(at(15, 31))


def test_live_adapter_equals_replay_byte_for_byte(tmp_path):
    m = load()
    ad = m.GSAdapter(tmp_path / "gs.db")
    ad.start_day(DAY, universe(), (15.0, 0.0))
    feed_adapter(ad)
    direct = []
    for c in m.DEFAULT_BRANCHES:
        e = sip.SipEngine(c)
        e.start_day(DAY, universe(), (15.0, 0.0))
        for _, _, kind, o in events():
            e.on_bar(o) if kind == "bar" else e.on_book("S0", o)
        e.on_clock(at(15, 31))
        direct.append(e.fingerprint())
    assert ad.fingerprints() == direct and ad.healthy
    res = ad.end_day()
    assert [r["branch"] for r in res] == ["P", "P", "M"] and res[0]["opportunities"][0]["status"] == "closed"


def test_failures_never_reach_the_bridge_and_disable_gs_for_the_day(tmp_path, monkeypatch):
    m = load()
    ad = m.GSAdapter(tmp_path / "gs.db")
    ad.start_day(DAY, universe(), (15.0, 0.0))
    monkeypatch.setattr(ad.engines[0], "on_book", lambda *a, **k: 1 / 0)
    feed_adapter(ad)                                                   # must not raise
    h = ad.health()
    assert not h["healthy"] and h["disabled_today"] and "ZeroDivisionError" in h["last_error"]
    n = len(ad.engines[1].execs)
    ad.on_quote("S0", {"buy": [], "sell": []}, None, None, at(15, 20))
    assert len(ad.engines[1].execs) == n                               # nothing runs for the rest of the day
    ad.start_day(DAY + timedelta(days=1), universe(), (15.0, 0.0))
    assert not ad.health()["disabled_today"]                           # a new day starts clean
    bad = m.GSAdapter(tmp_path / "no" / "such" / "dir" / "gs.db")      # even the store failing is contained
    assert not bad.healthy and bad.store is None


def test_adapter_persists_to_its_own_store_and_restarts_idempotently(tmp_path):
    m = load()
    p = tmp_path / "gs.db"
    for _ in range(2):                                                 # the second run = a restart replaying the day
        ad = m.GSAdapter(p)
        ad.start_day(DAY, universe(), (15.0, 0.0))
        feed_adapter(ad)
        ad.end_day()
        ad.store.close()
    s = gstore.Store(p)
    assert len(s.intents()) == 3 and len(s.executions()) == len({x["exec_id"] for x in s.executions()})
    assert s.latest_snapshot("day_equity", "GS-SIP-1/P/strict")["day"] == "2026-10-27"


def test_only_the_gs_glue_imports_the_adapter_and_it_imports_nothing_from_bridge():
    users = [f.relative_to(BRIDGE).as_posix() for f in list(BRIDGE.rglob("*.py")) if ".venv" not in f.parts
             and f != ADAPTER and "gs_adapter" in f.read_text(errors="ignore")]
    assert set(users) <= {"bridge/gs_live.py", "tests/test_gs_live.py"}      # wired only through bridge/gs_live.py
    svc = (BRIDGE / "bridge" / "service.py").read_text()
    assert "gs_adapter" not in svc and ("from .gs_live import GSLive" in svc or "gs_live" not in svc)
    tree = ast.parse(ADAPTER.read_text())
    mods = [n.module or "" for n in ast.walk(tree) if isinstance(n, ast.ImportFrom)] + \
           [a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not any(x == "bridge" or x.startswith("bridge.") or x.startswith(".") for x in mods)
    assert all(not (isinstance(n, ast.ImportFrom) and n.level) for n in ast.walk(tree))
