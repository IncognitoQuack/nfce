"""nfce_bridge/ops/collect.py and collect_chain.py (GS phase 0c): request-start, response-received and exchange times
are stored per request, old databases gain the columns, and the old columns keep their meaning. No network: the
HTTP call is a stub; the modules are loaded from their files without running main()."""
import importlib.util
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

OPS = Path(__file__).resolve().parents[2] / "nfce_bridge" / "ops"
sys.path.insert(0, str(OPS.parent))


def load(name):
    spec = importlib.util.spec_from_file_location(f"rec_{name}", OPS / f"{name}.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


class Resp:
    def __init__(self, data, status=200):
        self._d, self.status_code = data, status

    def raise_for_status(self):
        pass

    def json(self):
        return {"data": self._d}


def test_quote_recorder_stores_three_times_per_batch(tmp_path):
    c = load("collect")
    calls = []

    def fake_get(url, params, headers, timeout):
        calls.append(params["instrument_key"].count(",") + 1)
        return Resp({"NSE_EQ:X": {"instrument_token": "NSE_EQ|X", "last_price": 100.0, "volume": 5, "oi": 0,
                                  "depth": {"buy": [{"price": 99.9, "quantity": 10}], "sell": [{"price": 100.1, "quantity": 7}]},
                                  "last_trade_time": "1792751066454", "timestamp": "2026-10-27T09:30:00.123+05:30"}})
    batches = c.poll([f"K{i}" for i in range(500)], {}, get=fake_get)
    assert calls == [450, 50] and len(batches) == 2
    req, resp, data = batches[0]
    assert datetime.fromisoformat(req) <= datetime.fromisoformat(resp) and datetime.fromisoformat(req).tzinfo
    db = c.open_db(tmp_path / "q.db")
    rows = c.rows_of("2026-10-27T09:30:00+05:30", data, req, resp)
    db.executemany(f"insert into q values ({','.join('?' * 15)})", rows)
    r = db.execute("select ts, bid, ask, req_ts, resp_ts, exch_ts from q").fetchone()
    assert r[:3] == ("2026-10-27T09:30:00+05:30", 99.9, 100.1) and r[3] == req and r[4] == resp
    assert r[5] == "2026-10-27T09:30:00.123+05:30"


def test_old_databases_gain_the_columns(tmp_path):
    p = tmp_path / "old.db"
    con = sqlite3.connect(p)
    con.execute("create table q (ts text, key text, symbol text, last real, volume real, oi real, bid real, "
                "bid_qty real, ask real, ask_qty real, depth text, ltt text)")
    con.execute("create table chain (ts text, underlying text, expiry text, spot real, strike real, typ text, key text,"
                " ltp real, bid real, ask real, bid_qty real, ask_qty real, volume real, oi real, iv real, delta real,"
                " gamma real, theta real, vega real)")
    con.commit()
    con.close()
    for name, table in (("collect", "q"), ("collect_chain", "chain")):
        db = load(name).open_db(p)
        cols = [r[1] for r in db.execute(f"pragma table_info({table})")]
        assert cols[-3:] == ["req_ts", "resp_ts", "exch_ts"]
        db.close()


def test_chain_recorder_times_each_request_and_retries_429(tmp_path, monkeypatch):
    c = load("collect_chain")
    monkeypatch.setattr(c.time, "sleep", lambda s: None)
    seq = [Resp([], 429), Resp([{"underlying_spot_price": 22660.0, "strike_price": 22650.0,
                                 "call_options": {"instrument_key": "NSE_FO|1", "market_data": {"ltp": 290, "bid_price": 289.5,
                                                                                               "ask_price": 290.5, "bid_qty": 65,
                                                                                               "ask_qty": 130}},
                                 "put_options": {"market_data": {"bid_price": 190.0, "ask_price": 190.6}}}])]
    req, resp, data = c.get("chain", {}, {}, http_get=lambda *a, **k: seq.pop(0))
    assert len(data) == 1 and datetime.fromisoformat(req) <= datetime.fromisoformat(resp)
    rows = c.rows_of("2026-10-27T15:20:05", "NIFTY", "2026-11-03", data, req, resp)
    db = c.open_db(tmp_path / "c.db")
    db.executemany("insert into chain values (" + ",".join("?" * 22) + ")", rows)
    got = db.execute("select ts, typ, bid, ask, bid_qty, req_ts, resp_ts, exch_ts from chain order by typ").fetchall()
    assert got[0] == ("2026-10-27T15:20:05", "CE", 289.5, 290.5, 65.0, req, resp, None)
    assert got[1][1] == "PE" and got[1][5] == req
