"""Tests for tools/news_reaction.py on synthetic news and quote databases."""
import sqlite3
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools import news_reaction as nr  # noqa: E402


def make(tmp_path, events, path_fn):
    con = sqlite3.connect(tmp_path / "study_news_20261026.db")
    con.execute("create table news (seq_id text primary key, symbol text, fno integer, an_dt text, disseminated text,"
                " seen text, category text, text text, attachment text)")
    for i, (sym, t, seen, cat) in enumerate(events):
        con.execute("insert into news values (?,?,1,?,?,?,?,'','')", (str(i), sym, t, t, seen, cat))
    con.commit()
    con.close()
    con = sqlite3.connect(tmp_path / "study_quotes_20261026.db")
    con.execute("create table q (ts text, key text, symbol text, last real, volume real, oi real, bid real, bid_qty real,"
                " ask real, ask_qty real, depth text, ltt text)")
    times = pd.date_range("2026-10-26 09:15", "2026-10-26 15:30", freq="1min")
    for t in times:
        m = (t - times[0]).total_seconds() / 60
        for sym, mid in (("NSE_EQ:ABC", path_fn(m)), ("NSE_FO:NIFTY26OCTFUT", 25000.0)):
            con.execute("insert into q values (?, '', ?, 0, 0, 0, ?, 100, ?, 100, '', '')",
                        (t.strftime("%Y-%m-%dT%H:%M:%S+05:30"), sym, mid - 0.05, mid + 0.05))
    con.commit()
    con.close()


def test_group_names():
    assert nr.group("Bagging/Receiving of orders/contracts") == "orders"
    assert nr.group("Analysts/Institutional Investor Meet/Con.  Call Updates") == "analyst meet"
    assert nr.group("Copy of Newspaper Publication") == "other"


def test_reaction_and_rule_follow_a_jump(tmp_path):
    # ABC jumps 1% within 3 minutes of a 10:00 order-win announcement, then drifts up another 0.5% by 11:00
    def path(m):
        if m < 45:
            return 100.0
        return 101.0 + 0.5 * min(1.0, (m - 48) / 60) if m >= 48 else 100.0 + (m - 45) / 3
    make(tmp_path, [("ABC", "26-Oct-2026 10:00:00", "2026-10-26T10:00:20", "Bagging/Receiving of orders/contracts"),
                    ("ABC", "26-Oct-2026 09:05:00", "2026-10-26T09:05:20", "Press Release"),
                    ("XYZ", "26-Oct-2026 10:00:00", "2026-10-26T10:00:20", "Press Release")], path)
    r = nr.reactions("2026-10-26", tmp_path)
    assert len(r) == 1 and r["group"].iloc[0] == "orders"           # pre-open and non-F&O events are excluded
    assert r["ar5"].iloc[0] == pytest.approx(0.01 + 0.005 * 2 / 60, abs=1e-6)      # the jump plus 2 minutes of drift
    x = r.iloc[0]
    # the 10:05 quote completed AR5, so the entry is the NEXT quote (10:06 ask; GS phase 0 correction)
    assert x["traded"] and x["side"] == 1 and x["entry"] == pytest.approx(101.0 + 0.5 * 3 / 60 + 0.05)
    assert x["entry_t"] == pd.Timestamp("2026-10-26 10:06:00")
    assert x["exit_t"] <= pd.Timestamp("2026-10-26 11:00:00") and x["net_bp"] > 0
    s = nr.summary(r)
    assert s["rule_trades"] == 1 and s["by_group"]["orders"]["n"] == 1


def test_small_moves_are_not_traded_and_entry_waits_for_the_recorder(tmp_path):
    make(tmp_path, [("ABC", "26-Oct-2026 10:00:00", "2026-10-26T10:20:00", "Press Release")],
         lambda m: 100.0 + (0.6 if m >= 46 else 0.0))
    r = nr.reactions("2026-10-26", tmp_path).iloc[0]
    assert r["traded"] and r["entry_t"] >= pd.Timestamp("2026-10-26 10:20:00")    # seen 20 minutes late
    make2 = tmp_path / "small"
    make2.mkdir()
    make(make2, [("ABC", "26-Oct-2026 10:00:00", "2026-10-26T10:00:10", "Press Release")],
         lambda m: 100.0 + (0.2 if m >= 46 else 0.0))
    assert not nr.reactions("2026-10-26", make2).iloc[0]["traded"]


def test_no_events_gives_an_empty_summary(tmp_path):
    make(tmp_path, [], lambda m: 100.0)
    assert nr.summary(nr.reactions("2026-10-26", tmp_path)) == {"events": 0, "by_group": {}, "rule_trades": 0}


def test_one_trade_at_a_time_per_stock(tmp_path):
    make(tmp_path, [("ABC", "26-Oct-2026 10:00:00", "2026-10-26T10:00:10", "Press Release"),
                    ("ABC", "26-Oct-2026 10:20:00", "2026-10-26T10:20:10", "Press Release")],
         lambda m: 100.0 + (0.6 if m >= 46 else 0.0) + (0.6 if m >= 66 else 0.0))
    r = nr.reactions("2026-10-26", tmp_path)
    assert r["traded"].tolist() == [True, False] and r["skipped"].iloc[1] == "already in a trade"


def test_entry_never_reuses_the_signal_quote_and_the_old_path_reproduces(tmp_path, monkeypatch):
    def path(m):
        return 100.0 if m < 47 else 101.0
    make(tmp_path, [("ABC", "26-Oct-2026 10:00:00", "2026-10-26T10:00:20", "Press Release")], path)
    new = nr.reactions("2026-10-26", tmp_path).iloc[0]
    assert new["entry_t"] == pd.Timestamp("2026-10-26 10:06:00")
    monkeypatch.setattr(nr, "CAUSAL_FIX", False)
    old = nr.reactions("2026-10-26", tmp_path).iloc[0]
    assert old["entry_t"] == pd.Timestamp("2026-10-26 10:05:00")      # the registered pilot behaviour


def test_stale_nifty_quotes_void_the_signal(tmp_path):
    make(tmp_path, [("ABC", "26-Oct-2026 10:00:00", "2026-10-26T10:00:20", "Press Release")],
         lambda m: 100.0 if m < 47 else 101.0)
    con = sqlite3.connect(tmp_path / "study_quotes_20261026.db")       # NIFTY stops quoting at 09:40
    con.execute("delete from q where symbol like 'NSE_FO:%' and ts > '2026-10-26T09:40:00'")
    con.commit()
    con.close()
    r = nr.reactions("2026-10-26", tmp_path)
    assert r.empty                                                    # the NIFTY base quote is 20 minutes old
