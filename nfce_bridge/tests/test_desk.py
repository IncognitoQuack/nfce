"""The trading desk (ops/desk.py): read-only, and its figures add up. Uses a temporary database only."""
import json
import sqlite3

import pytest

from ops import desk

DAY = "2026-10-27"


@pytest.fixture()
def db(tmp_path):
    p = tmp_path / "nfce.db"
    con = sqlite3.connect(p)
    con.executescript("""
    CREATE TABLE account_equity (acct TEXT, ts TEXT, equity REAL, cash REAL, open_value REAL, n_open INTEGER);
    CREATE TABLE account_fills (id INTEGER PRIMARY KEY, acct TEXT, ts TEXT, sid TEXT, symbol TEXT, action TEXT, lots INTEGER,
        units INTEGER, price REAL, cash_flow REAL, fees REAL, realized REAL, reason TEXT, cash_after REAL);
    CREATE TABLE paper_trades (id INTEGER PRIMARY KEY, book TEXT, sid TEXT, opened TEXT, closed TEXT, underlying TEXT, tf TEXT,
        decision TEXT, grade TEXT, side INTEGER, entry REAL, sl REAL, t1 REAL, t2 REAL, t3 REAL, status TEXT, exit_reason TEXT,
        gross_pts REAL, net_pts REAL, r_pts REAL, flags TEXT, state TEXT);
    CREATE TABLE option_trades (id INTEGER PRIMARY KEY, sid TEXT, book TEXT, underlying TEXT, key TEXT, strike REAL, type TEXT,
        expiry TEXT, units INTEGER, opened TEXT, entry REAL, closed TEXT, exit REAL, status TEXT, reason TEXT, fees REAL,
        net_inr REAL, r_inr REAL, leg TEXT);
    CREATE TABLE sent_messages (id INTEGER PRIMARY KEY, ts TEXT, ok INTEGER, text TEXT);
    CREATE TABLE events (id INTEGER PRIMARY KEY, ts TEXT, source TEXT, raw TEXT);
    CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT);
    CREATE TABLE account_positions (id INTEGER PRIMARY KEY, acct TEXT, sid TEXT, status TEXT, state TEXT);
    """)
    con.execute("INSERT INTO account_positions (acct, sid, status, state) VALUES ('5L', 's1', 'OPEN', ?)",
                (json.dumps({"symbol": "NIFTY 22750 CE", "key": "NSE_FO|1", "under_key": "NSE_INDEX|Nifty 50",
                             "side": 1, "lots": 1, "rem_lots": 1, "lot_units": 65, "entry": 200.0}),))
    rows = [("5L", "2026-10-26T15:30:00+05:30", 500000, 500000, 0, 0),
            ("5L", f"{DAY}T10:00:00+05:30", 498000, 440000, 58000, 1),
            ("5L", f"{DAY}T15:30:00+05:30", 496000, 496000, 0, 0),
            ("CONC", "2026-10-26T15:30:00+05:30", 500000, 500000, 0, 0),
            ("CONC", f"{DAY}T15:30:00+05:30", 510000, 510000, 0, 0)]
    con.executemany("INSERT INTO account_equity VALUES (?,?,?,?,?,?)", rows)
    con.execute("INSERT INTO account_fills (acct, ts, symbol, action, lots, price, fees, realized, reason) VALUES "
                "('5L', ?, 'NIFTY 22650 CE', 'SELL', 1, 150.0, 60.0, -4000.0, 'stop')", (f"{DAY}T11:00:00+05:30",))
    st = json.dumps({"lot_units": 100, "lots": 1})
    con.executemany("INSERT INTO paper_trades (book, opened, closed, underlying, side, entry, status, exit_reason, net_pts, "
                    "state) VALUES (?,?,?,?,?,?,?,?,?,?)",
                    [("scanner", f"{DAY}T09:21:00+05:30", f"{DAY}T10:00:00+05:30", "INFY", -1, 1135.9, "CLOSED", "stop", -5.0, st),
                     ("scanner", f"{DAY}T09:30:00+05:30", "", "TCS", -1, 2474.1, "OPEN", "", None, st),
                     ("stock3m", "2026-10-26T11:00:00+05:30", "", "OLD", 1, 1.0, "CLOSED", "T1", 9.0, st)])
    con.execute("INSERT INTO option_trades (sid, book, opened, status, net_inr) VALUES ('x', 'scanner', ?, 'CLOSED', 700.0)",
                (f"{DAY}T09:21:00+05:30",))
    con.execute("INSERT INTO kv VALUES ('account_5L_streak_2026-10-27', '2')")
    con.execute("INSERT INTO kv VALUES ('account_5L_dg_2026-10-27', ?)", (json.dumps({"peak": 12000, "halt": "13:05"}),))
    con.commit()
    con.close()
    return p


def test_accounts_day_pnl_limits_and_curve(db):
    s = desk.snapshot(DAY, db=db, gsdb=db.parent / "none.db", with_live=False)
    a = {x["name"]: x for x in desk.accounts(desk.ro(db), DAY, {"5L": "base", "CONC": "concentrated"})}
    assert a["5L"]["day_pnl"] == -4000 and a["5L"]["start_equity"] == 500000
    assert a["5L"]["limits"]["daily_loss"]["used"] == pytest.approx(4000 / 15000)       # 3% of 5 L = 15,000
    assert a["5L"]["limits"]["streak"]["losses"] == 2 and a["5L"]["limits"]["give_back"]["halted"]
    assert [c[0] for c in a["5L"]["curve"]] == ["10:00", "15:30"]
    assert a["CONC"]["limits"]["open"]["cap"] == 3 and a["CONC"]["limits"]["daily_loss"]["cap"] == 50000
    assert a["5L"]["fees"] == 60 and a["5L"]["exits"] == 1 and a["5L"]["won"] == 0
    assert s["gs"] == {"available": False}


def test_books_attribute_only_the_day_and_split_legs(db):
    b = {(x["book"], x["leg"]): x for x in desk.books(desk.ro(db), DAY)}
    assert b[("scanner", "futures")] == {"book": "scanner", "leg": "futures", "n": 2, "open": 1, "won": 0, "closed_pnl": -500.0}
    assert b[("scanner", "options")]["closed_pnl"] == 700.0
    assert ("stock3m", "futures") not in b                                    # yesterday's trade is not today's P&L
    sig = desk.signals(desk.ro(db), DAY)
    assert {x["symbol"] for x in sig} == {"INFY", "TCS"} and [x["pnl"] for x in sig if x["symbol"] == "TCS"] == [None]


def test_risk_marks_open_positions_from_the_stream(db, tmp_path, monkeypatch):
    from ops import stream
    s = tmp_path / "stream.db"
    con = stream.open_db(s)
    row = lambda key, ltp, bid, ask, delta, gamma, vega, theta: (  # noqa: E731
        "2026-10-27T10:00:00.000+05:30", key, "fullFeed", ltp, 0, 0, ltp, bid, 1, ask, 1, None, 0, 0, 0, 0, 0, None, 0,
        15.0, delta, 0, gamma, vega, theta)
    con.executemany("INSERT INTO tick VALUES (" + ",".join("?" * 25) + ")",
                    [row("NSE_FO|1", 210.0, 209.0, 211.0, 0.5, 0.0004, 12.0, -9.0),
                     row("NSE_INDEX|Nifty 50", 22760.0, None, None, None, None, None, None)])
    con.commit()
    con.close()
    monkeypatch.setattr(desk, "stream_path", lambda day: s)
    r = desk.risk_section(desk.ro(db), DAY)
    p = r["positions"][0]
    assert (p["mark"], p["mark_source"], p["unrealized"]) == (209.0, "bid", pytest.approx(9.0 * 65))
    assert r["scenario_included"] == 1 and r["exposure"]["total"]["vega"] == pytest.approx(12.0 * 65)


def test_alert_rules():
    from datetime import datetime
    snap = {"health": {"up": True, "problems": ["no fresh futures quotes for SENSEX", "chain stale"],
                       "poll_beat": "2026-10-28T10:00:00+05:30", "gs": "NOT RUN today: x"},
            "system": {"token_ok": True, "on_battery": True, "battery_pct": 12},
            "accounts": [{"name": "5L", "limits": {"daily_loss": {"used": 0.85}, "give_back": {"halted": True},
                                                   "streak": {"losses": 2}}}],
            "stream": {"available": True, "age_s": 45}, "risk": {"positions": [{"acct": "5L", "symbol": "X", "mark": None}]},
            "books": {"error": "boom"}}
    al = desk.alerts(snap, datetime(2026, 10, 28, 10, 2, tzinfo=desk.IST))
    text = " | ".join(f"{a['level']}:{a['text']}" for a in al)
    assert al[0]["level"] == "crit" and "battery: 12%" in text.lower()
    assert "SENSEX" not in text and "warn:Health: chain stale" in text and "poll loop silent for 120s" in text
    assert "warn:GS: NOT RUN" in text and "85% of the daily loss" in text and "info:5L: give-back" in text
    assert "Stream silent for 45s" in text and "no live mark" in text and "section 'books' failed" in text
    assert desk.alerts({"health": {"up": False}}, datetime(2026, 10, 28, 20, 0, tzinfo=desk.IST)) == []


def test_a_failing_section_does_not_break_the_snapshot(db, monkeypatch):
    monkeypatch.setattr(desk, "books", lambda con, day: 1 / 0)
    s = desk.snapshot(DAY, db=db, gsdb=db.parent / "none.db", with_live=False, with_research=False)
    assert s["books"]["error"].startswith("ZeroDivisionError") and len(s["accounts"]) == 2
    assert any("books" in a["text"] for a in s["alerts"])


def test_power_is_read_as_on_charger_first(monkeypatch):
    """panel.power() returns (on charger, %). On 27 Oct the desk read it backwards and showed 'on charger' on battery."""
    from bridge import panel
    monkeypatch.setattr(panel, "token_line", lambda: (True, "ok"))
    monkeypatch.setattr(panel, "power", lambda: (False, 71))
    assert desk.system()["on_battery"] is True and desk.system()["battery_pct"] == 71
    monkeypatch.setattr(panel, "power", lambda: (True, 100))
    assert desk.system()["on_battery"] is False
    monkeypatch.setattr(panel, "power", lambda: (None, None))
    assert desk.system()["on_battery"] is None


def test_the_desk_cannot_write(db):
    with pytest.raises(sqlite3.OperationalError):
        desk.ro(db).execute("INSERT INTO kv VALUES ('x', '1')")


def test_one_nan_anywhere_cannot_take_the_desk_down():
    # 28 Oct 08:57: a pending OVN row's NaN made /api/all return 500 on every tab
    snap = {"research": {"overnight": {"v2": [{"day": "2026-10-28", "units": float("nan")}]}},
            "risk": {"positions": [{"unrealized": float("inf"), "mark": 1.5}]}, "n": 3}
    safe = desk.json_safe(snap)
    json.dumps(safe, allow_nan=False)
    assert safe["research"]["overnight"]["v2"][0]["units"] is None and safe["risk"]["positions"][0]["mark"] == 1.5
    assert safe["n"] == 3


def test_roles_tokens_and_the_wifi_rule(tmp_path, monkeypatch):
    # owner OK 28 Oct: the desk on the Wi-Fi, VIEW and CONTROL tokens; this Mac needs none
    assert desk.role_of("127.0.0.1", "", "v" * 32, "c" * 32) == "control"
    assert desk.role_of("192.168.1.9", "", "v" * 32, "c" * 32) is None
    assert desk.role_of("192.168.1.9", "v" * 32, "v" * 32, "c" * 32) == "view"
    assert desk.role_of("192.168.1.9", "c" * 32, "v" * 32, "c" * 32) == "control"
    assert desk.role_of("192.168.1.9", "x", "", "") is None                  # no tokens set: nobody remote
    assert desk.role_of("192.168.1.9", "ünïcode", "v" * 32, "c" * 32) is None  # odd input cannot crash it
    env = tmp_path / ".env"
    env.write_text("WEBHOOK_SECRET=keep\nDESK_VIEW_TOKEN=already\n")
    assert desk.init_tokens(env) == ["DESK_CONTROL_TOKEN", "DESK_ADMIN_SECRET"]
    assert desk.env_value("DESK_VIEW_TOKEN", env) == "already" and desk.env_value("WEBHOOK_SECRET", env) == "keep"
    assert len(desk.env_value("DESK_CONTROL_TOKEN", env)) >= 30 and desk.init_tokens(env) == []


def test_remote_needs_a_token_and_view_cannot_control(monkeypatch):
    from fastapi.testclient import TestClient
    vals = {"DESK_VIEW_TOKEN": "V" * 32, "DESK_CONTROL_TOKEN": "C" * 32, "DESK_ADMIN_SECRET": "S" * 32}
    monkeypatch.setattr(desk, "env_value", lambda k, env_file=None: vals.get(k, ""))
    monkeypatch.setattr(desk, "snapshot", lambda day=None: {"day": "2026-10-28", "x": float("nan")})
    sent = {}

    class R:
        status_code = 200

        @staticmethod
        def json():
            return {"ok": True, "result": ["5L: sold S1 (MANUAL close (desk))"]}

    def post(url, headers, json, timeout):
        sent.update(url=url, headers=headers, body=json)
        return R()
    import httpx
    monkeypatch.setattr(httpx, "post", post)
    c = TestClient(desk.app(lan=True))                       # TestClient's host is "testclient": a remote device
    assert c.get("/").status_code == 200                     # the page itself holds no data
    assert c.get("/api/all").status_code == 401
    r = c.get("/api/all", headers={"X-Desk-Token": "V" * 32})
    assert r.status_code == 200 and r.json()["role"] == "view" and r.json()["x"] is None and "links" not in r.json()
    body = {"action": "close", "acct": "5L", "sid": "S1"}
    assert c.post("/api/control", json=body, headers={"X-Desk-Token": "V" * 32}).status_code == 403
    assert sent == {}
    r = c.post("/api/control", json=body, headers={"X-Desk-Token": "C" * 32, "User-Agent": "Mozilla (iPhone)"})
    assert r.status_code == 200 and sent["url"].endswith("/admin/action")
    assert sent["headers"] == {"X-Admin-Secret": "S" * 32} and sent["body"]["device"] == "testclient iPhone"
    assert {k: sent["body"][k] for k in ("action", "acct", "sid")} == body


def test_performance_uses_each_accounts_own_capital():
    # 28 Oct: G20 starts at ₹20 L; a fixed ₹5 L base would show it at +300%
    from ops import eod_report
    con = sqlite3.connect(":memory:")
    con.executescript("CREATE TABLE kv (k TEXT PRIMARY KEY, v TEXT); "
                      "CREATE TABLE account_equity (acct TEXT, ts TEXT, equity REAL, cash REAL, open_value REAL, n_open INTEGER);")
    con.execute("INSERT INTO kv VALUES ('account_G20_capital', '2000000.0')")
    con.executemany("INSERT INTO account_equity VALUES (?,?,?,0,0,0)",
                    [("G20", "2026-10-29T15:30:00", 2_010_000.0), ("5L", "2026-10-29T15:30:00", 495_000.0)])
    p = eod_report.performance(con, "2026-10-29")
    assert round(p["G20"]["total_pct"], 3) == 0.5 and p["G20"]["capital"] == 2_000_000
    assert round(p["5L"]["total_pct"], 3) == -1.0


def test_live_snapshot_survives_a_missing_table(db):
    # the Trade tab refreshes every second: one failing part must not blank it (the fixture has no signals table)
    snap = desk.live_snapshot(DAY, db=db)
    assert snap["signals"] == [] and any(e.startswith("signals:") for e in snap["errors"])
    assert isinstance(snap["accounts"], list) and isinstance(snap["fills"], list)
    json.dumps(desk.json_safe(snap), allow_nan=False)


def test_chart_bars_indicators_and_signal_levels(db, tmp_path):
    st = tmp_path / "stream.db"
    con = sqlite3.connect(st)
    con.execute("CREATE TABLE tick (recv_ts TEXT, key TEXT, ltp REAL, vtt REAL, bid1 REAL)")
    ticks = [("2026-10-27T09:15:01+05:30", 100.0, 1000), ("2026-10-27T09:15:40+05:30", 102.0, 1500),
             ("2026-10-27T09:16:05+05:30", 101.0, 1600), ("2026-10-27T09:16:50+05:30", 99.0, 2600)]
    con.executemany("INSERT INTO tick VALUES (?, 'NSE_EQ|X', ?, ?, 0)", ticks)
    con.commit()
    desk._KEYS.clear()
    desk._KEYS.update({"XYZ": "NSE_EQ|X"})
    c2 = sqlite3.connect(db)
    c2.execute("INSERT INTO paper_trades (book, sid, opened, underlying, side, entry, sl, t1, status) VALUES "
               "('stock3m', 's', '2026-10-27T09:16:00+05:30', 'XYZ', 1, 105.0, 104.0, 107.0, 'OPEN')")
    c2.commit()
    d = desk.chart_data(DAY, "xyz", db=db, stream=st)
    assert [(b["t"], b["o"], b["h"], b["l"], b["c"], b["v"]) for b in d["bars"]] == \
        [("09:15", 100.0, 102.0, 100.0, 102.0, 500.0), ("09:16", 101.0, 101.0, 99.0, 99.0, 1100.0)]
    assert d["has_volume"] and abs(d["vwap"][0] - (102 + 100 + 102) / 3) < 1e-9
    assert d["ema9"][0] == 102.0 and d["ema9"][1] < 102.0
    sg = d["signals"][0]                       # futures levels moved to the spot close of 09:16 (99), same distances
    assert (sg["entry"], sg["sl"], sg["t1"]) == (99.0, 98.0, 101.0)
    assert "error" in desk.chart_data(DAY, "NOPE", db=db, stream=st)
    desk._KEYS.clear()


def test_rsi_is_wilder_and_bounded():
    r = desk.rsi([1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 14], 14)
    assert r[13] is None and r[14] == 100.0 and 0 < r[15] < 100
