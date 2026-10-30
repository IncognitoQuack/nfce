"""Streaming feed: the runtime-built V3 messages match Upstox's .proto exactly, and frames become the right rows.
No network: frames are built locally with the same classes."""
import json
import re

from bridge import feed_proto as fp
from ops import stream


def test_every_field_of_the_official_proto_is_built_with_its_number_and_type():
    text = fp.PROTO.read_text()
    C = fp.classes()
    blocks = dict(re.findall(r"message\s+(\w+)\s*\{(.*?)\n\}", text, re.S))
    assert set(blocks) == set(C)
    for name, body in blocks.items():
        want = {}
        for typ, fname, num in re.findall(r"^\s*(?:repeated\s+)?([\w.]+(?:<[\w, ]+>)?)\s+(\w+)\s*=\s*(\d+)\s*;", body, re.M):
            want[fname] = int(num)
        got = {f.name: f.number for f in C[name].DESCRIPTOR.fields}
        assert got == want, name
    ff = C["MarketFullFeed"].DESCRIPTOR.fields_by_name
    assert ff["casEligible"].type == ff["casEligible"].TYPE_BOOL and ff["vtt"].type == ff["vtt"].TYPE_INT64
    assert C["LTPC"].DESCRIPTOR.fields_by_name["iep"].message_type.full_name == "google.protobuf.DoubleValue"
    assert C["FeedResponse"].DESCRIPTOR.fields_by_name["feeds"].message_type.GetOptions().map_entry


def _frame():
    C = fp.classes()
    r = C["FeedResponse"](type=1, currentTs=1793090000123)
    m = r.feeds["NSE_FO|48986"].fullFeed.marketFF
    m.ltpc.ltp, m.ltpc.ltt, m.ltpc.ltq, m.ltpc.cp = 285.95, 1793090000000, 1350, 290.1
    for i in range(5):
        q = m.marketLevel.bidAskQuote.add()
        q.bidP, q.bidQ, q.askP, q.askQ = 285.9 - i / 20, 100 * (i + 1), 286.0 + i / 20, 50 * (i + 1)
    m.vtt, m.oi, m.atp, m.tbq, m.tsq, m.iep, m.casEligible = 9_000_000, 1.2e7, 286.4, 5e5, 6e5, 286.1, True
    r.feeds["NSE_INDEX|Nifty 50"].fullFeed.indexFF.ltpc.ltp = 22760.75
    g = r.feeds["NSE_FO|1"].firstLevelWithGreeks
    g.ltpc.ltp, g.firstDepth.bidP, g.firstDepth.askP, g.oi, g.iv, g.optionGreeks.delta = 209.9, 209.35, 209.9, 1e6, 15.2, 0.52
    g.optionGreeks.gamma, g.optionGreeks.vega, g.optionGreeks.theta = 0.0004, 12.5, -9.1
    r.marketInfo.segmentStatus["NSE_EQ"] = 4                                      # CLOSING_START
    r.marketInfo.casMarketStatus["NSE_EQ"].status = "CLOSING_START"
    return r.SerializeToString()


def test_frames_become_tick_and_market_info_rows():
    ticks, info = stream.rows_of(fp.decode(_frame()), "2026-10-28T15:16:00.000+05:30")
    by = {t[1]: t for t in ticks}
    fut = by["NSE_FO|48986"]
    assert fut[2] == "fullFeed" and fut[3] == 285.95 and fut[4] == 1793090000000 and fut[7] == 285.9 and fut[9] == 286.0
    assert len(json.loads(fut[11])) == 5 and fut[17] == 286.1 and fut[18] == 1 and fut[21] == 1793090000123
    assert by["NSE_INDEX|Nifty 50"][3] == 22760.75 and by["NSE_INDEX|Nifty 50"][11] is None
    assert by["NSE_FO|1"][2] == "firstLevelWithGreeks" and by["NSE_FO|1"][20] == 0.52
    assert by["NSE_FO|1"][22:25] == (0.0004, 12.5, -9.1) and by["NSE_FO|48986"][22] is None   # gamma, vega, theta
    body = json.loads(info[0][2])
    assert info[0][1] == "market_info" and body["segment"]["NSE_EQ"] == 4 and body["cas"]["NSE_EQ"]["status"] == "CLOSING_START"


def test_subscription_is_binary_json_with_mode_and_keys(tmp_path):
    msg = json.loads(stream.subscription(["NSE_INDEX|Nifty 50"], "full"))
    assert msg["method"] == "sub" and msg["data"] == {"mode": "full", "instrumentKeys": ["NSE_INDEX|Nifty 50"]}
    assert isinstance(stream.subscription([]), bytes)
    db = stream.open_db(tmp_path / "s.db")
    assert {r[1] for r in db.execute("pragma table_info(tick)")} >= {"recv_ts", "ltp", "ltt", "iep", "cas", "depth"}


def test_book_keys_follow_only_open_positions(tmp_path):
    import sqlite3
    p = tmp_path / "nfce.db"
    con = sqlite3.connect(p)
    con.execute("CREATE TABLE account_positions (id INTEGER PRIMARY KEY, acct TEXT, sid TEXT, status TEXT, state TEXT)")
    con.execute("INSERT INTO account_positions (acct, sid, status, state) VALUES ('5L','a','OPEN',?)",
                (json.dumps({"key": "NSE_FO|1", "under_key": "NSE_INDEX|Nifty 50"}),))
    con.execute("INSERT INTO account_positions (acct, sid, status, state) VALUES ('5L','b','CLOSED',?)",
                (json.dumps({"key": "NSE_FO|2", "under_key": "NSE_EQ|X"}),))
    con.commit()
    con.close()
    assert stream.book_keys(p) == {"NSE_FO|1", "NSE_INDEX|Nifty 50"}
    assert stream.book_keys(tmp_path / "missing.db") == set()


def test_a_bad_frame_is_skipped_and_buffered_ticks_survive_a_drop(tmp_path, monkeypatch):
    import asyncio
    import sys
    import types
    frames = [b"\xff\xff not protobuf", _frame()]
    connects = []

    class FakeWS:
        async def send(self, data):
            pass

        async def recv(self):
            if frames:
                return frames.pop(0)
            raise ConnectionError("server closed")             # the connection drops after two frames

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

    fake = types.SimpleNamespace(connect=lambda url, **kw: connects.append(url) or FakeWS())
    monkeypatch.setitem(sys.modules, "websockets", fake)
    monkeypatch.setattr(stream, "authorize", lambda token: "wss://test")
    out = tmp_path / "s.db"
    asyncio.run(stream.run(str(out), "23:59", "full", ["NSE_FO|48986"], "tok", max_minutes=0.01))
    import sqlite3
    db = sqlite3.connect(out)
    kinds = [r[0] for r in db.execute("SELECT kind FROM info")]
    assert db.execute("SELECT COUNT(*) FROM tick").fetchone()[0] == 3      # the good frame's ticks were written
    assert "bad_frame" in kinds and kinds.count("error") == 1             # skipped; only the drop is an error
    assert len(connects) == 1                                             # no reconnect because of the bad frame


def test_proto_file_is_the_verified_official_one():
    import hashlib
    assert hashlib.sha256(fp.PROTO.read_bytes()).hexdigest() == fp.PROTO_SHA256
