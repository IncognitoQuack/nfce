"""End-of-day report: since-inception stats, attribution and resilience to a failing section (temporary DB only)."""
import json
import sqlite3

import pytest

from ops import eod_report as er

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
    """)
    for d, e in (("2026-10-22", 490000), ("2026-10-23", 485000), ("2026-10-26", 495000), ("2026-10-27", 495000)):
        con.execute("INSERT INTO account_equity VALUES ('5L', ?, ?, ?, 0, 0)", (f"{d}T10:00:00+05:30", e + 1000, e))
        con.execute("INSERT INTO account_equity VALUES ('5L', ?, ?, ?, 0, 0)", (f"{d}T15:30:00+05:30", e, e))
    st = json.dumps({"lot_units": 100, "lots": 1})
    con.executemany("INSERT INTO paper_trades (book, opened, side, status, exit_reason, net_pts, state) VALUES (?,?,?,?,?,?,?)",
                    [("scanner", f"{DAY}T10:15:00+05:30", -1, "CLOSED", "stop", -10.0, st),
                     ("scanner", f"{DAY}T10:15:00+05:30", -1, "CLOSED", "T1 (all lots)", 6.0, st),
                     ("stock3m", f"{DAY}T11:00:00+05:30", 1, "OPEN", "", None, st)])
    con.execute("INSERT INTO option_trades (sid, book, type, opened, status, reason, net_inr) VALUES "
                "('x', 'scanner', 'PE', ?, 'CLOSED', 'stop', -300.0)", (f"{DAY}T10:16:00+05:30",))
    con.commit()
    con.close()
    return p


def test_performance_since_inception(db):
    p = er.performance(er.desk.ro(db), DAY)["5L"]
    assert p["days"] == 4 and p["equity"] == 495000 and p["total_pct"] == pytest.approx(-1.0)
    assert p["max_dd_pct"] == pytest.approx(-3.0)                        # 500,000 → 485,000
    assert (p["best_day"], p["worst_day"], p["pos_days"], p["flat_days"]) == (10000, -10000, 1, 1)


def test_attribution_groups_closed_trades_only(db):
    a = er.attribution(er.desk.ro(db), DAY)
    assert a["by_book"]["scanner futures"] == {"n": 2, "won": 1, "net": pytest.approx(-400.0)}
    assert a["by_direction"]["options SELL"]["net"] == -300.0
    assert a["by_exit"]["futures stop"]["net"] == pytest.approx(-1000.0) and "stock3m futures" not in a["by_book"]


def test_a_failing_section_is_reported_not_fatal(db, monkeypatch):
    monkeypatch.setattr(er, "research", lambda day: (_ for _ in ()).throw(RuntimeError("boom")))
    monkeypatch.setattr(er, "market", lambda day: {})
    rep = er.build(DAY, db=db)
    assert rep["research"]["error"].startswith("RuntimeError") and rep["performance"]["5L"]["days"] == 4
    text = er.render(rep)
    assert "# End-of-day analysis: 2026-10-27" in text and "scanner futures" in text
