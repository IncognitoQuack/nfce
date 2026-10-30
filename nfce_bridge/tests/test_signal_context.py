"""Shadow signal context: every field is taken as of the signal time, alignment is relative to the signal's side,
and no outcome is stored. Synthetic stream / chain / news / brief only."""
import json
import sqlite3

import pandas as pd

from ops import signal_context as sc
from ops import stream

T = "2026-10-28T10:15:00.000+05:30"


def _stream(tmp_path):
    p = tmp_path / "s.db"
    con = stream.open_db(p)
    depth = json.dumps([[999.9, 900, 1000.1, 100]] * 5)
    row = lambda ts, key, ltp, cp, bid=None, ask=None, d=None: (  # noqa: E731
        ts, key, "fullFeed", ltp, 0, 0, cp, bid, 1, ask, 1, d, 0, 0, 0, 0, 0, None, 1, None, None, 0, None, None, None)
    con.executemany("INSERT INTO tick VALUES (" + ",".join("?" * 25) + ")", [
        row("2026-10-28T10:14:00.000+05:30", "NSE_EQ|A", 1000.0, 990.0, 999.9, 1000.1, depth),     # +1.01%, bids heavy
        row("2026-10-28T10:16:00.000+05:30", "NSE_EQ|A", 900.0, 990.0, 899.9, 900.1, depth),       # AFTER t: ignored
        row("2026-10-28T10:14:00.000+05:30", "NSE_EQ|B", 50.0, 51.0),                             # down
        row("2026-10-28T10:14:00.000+05:30", "NSE_EQ|C", 20.0, 19.0),                             # up
        row("2026-10-28T10:14:00.000+05:30", sc.NIFTY, 22800.0, 22750.0),
        row("2026-10-28T10:14:00.000+05:30", sc.VIX, 16.0, 17.0)])
    con.commit()
    con.close()
    return sqlite3.connect(f"file:{p}?mode=ro", uri=True)


def test_context_is_as_of_the_signal_time_and_aligned_to_its_side(tmp_path, monkeypatch):
    from bridge import regime
    monkeypatch.setattr(regime, "_safe_history", lambda: tuple(float(x) for x in range(10, 30)))   # no real files
    s = _stream(tmp_path)
    news = pd.DataFrame([{"symbol": "AAA", "fno": 1, "disseminated": "28-Oct-2026 09:40:00", "category": "Financial Results",
                          "text": "Results"},
                         {"symbol": "AAA", "fno": 1, "disseminated": "28-Oct-2026 11:00:00", "category": "x", "text": "later"}])
    brief = {"AAA": {"cats": ["RESULTS"], "results": {"pat_yoy": 0.5, "rev_yoy": 0.2}}}
    sig = {"sid": "S1", "t": T, "book": "stock3m", "symbol": "AAA", "side": 1, "entry": 1000.0}
    r = sc.context(sig, s, None, news, {"AAA"}, {"AAA": "NSE_EQ|A"}, brief)
    assert round(r["stock_chg_pct"], 2) == 1.01 and round(r["spread_bp"], 1) == 2.0 and r["imb_l1"] == 0.8
    assert round(r["nifty_chg_pct"], 3) == 0.220 and r["vix"] == 16.0 and r["breadth"] == 2 / 3      # A and C up
    assert r["news_count_day"] == 1.0 and r["news_results"] == 1.0 and r["results_today"] == 1        # 11:00 ignored
    assert r["brief_cats"] == "RESULTS" and r["results_pat_yoy"] == 0.5
    assert (r["book_aligned"], r["market_aligned"], r["breadth_aligned"]) == (1, 1, 1)
    assert (r["regime_vol"], r["regime_trend"], r["vix_pct"]) == ("normal", "mixed", 7 / 20)   # VIX 16 of 10..29
    short = sc.context(sig | {"side": -1}, s, None, None, set(), {"AAA": "NSE_EQ|A"})
    assert (short["book_aligned"], short["market_aligned"], short["breadth_aligned"]) == (0, 0, 0)
    assert "net" not in r and "pnl" not in r and "outcome" not in r                              # no outcomes stored


def test_sector_fields_fill_only_when_a_sector_map_is_given(tmp_path, monkeypatch):
    from bridge import regime
    monkeypatch.setattr(regime, "_safe_history", lambda: ())
    s = _stream(tmp_path)
    keys = {"AAA": "NSE_EQ|A", "BBB": "NSE_EQ|B", "CCC": "NSE_EQ|C"}
    sig = {"sid": "S3", "t": T, "book": "scanner", "symbol": "BBB", "side": -1, "entry": 50.0}
    sectors = {"AAA": "IT", "BBB": "IT", "CCC": "METAL"}             # IT peers: A +1.01%, B −1.96%
    r = sc.context(sig, s, None, None, set(), keys, None, sectors)
    assert r["sector"] == "IT" and round(r["sector_chg_pct"], 2) == round((1000 / 990 - 1 + 50 / 51 - 1) * 50, 2)
    assert r["sector_aligned"] == 1                                  # a SELL in a falling sector
    none = sc.context(sig, s, None, None, set(), keys, None, {})
    assert none["sector"] is None and none["sector_chg_pct"] is None and none["sector_aligned"] is None
    p = tmp_path / "map.csv"
    p.write_text("symbol,sector\nAAA,IT\nBBB, IT \nCCC,\n")
    assert sc.sector_map(p) == {"AAA": "IT", "BBB": "IT"} and sc.sector_map(tmp_path / "none.csv") == {}


def test_missing_sources_give_empty_fields_not_errors():
    sig = {"sid": "S2", "t": T, "book": "scanner", "symbol": "ZZZ", "side": -1, "entry": 10.0}
    r = sc.context(sig, None, None, None, set(), {})
    assert r["stock_chg_pct"] is None and r["book_aligned"] is None and r["sector"] is None
    assert sc.summary([r])["with_stream"] == 0
