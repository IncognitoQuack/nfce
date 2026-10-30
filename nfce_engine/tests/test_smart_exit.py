"""SMART-EXIT-1 walker (tools/smart_exit.py, ../evidence/smart_exit_1_protocol.md) on hand-made 3m bars.
Long or short, entry 100, R0 = 2: +0.5R = 101, +0.3R = 100.6, -1R = 98."""
import pandas as pd
import pytest

from tools.smart_exit import walk_smart as w


def bars(rows, t0=600):
    return pd.DataFrame([dict(open=o, high=h, low=l, close=c, hm=t0 + 3 * i) for i, (o, h, l, c) in enumerate(rows)])


def test_quick_books_sell_at_their_level():
    up = bars([(100, 100.6, 99.8, 100.4), (100.4, 101.2, 100.2, 101)])
    assert w(up, 0, 1, 100, 2, "S2")[0] == 100.6 and w(up, 0, 1, 100, 2, "S1")[0] == 101.0
    assert w(bars([(100, 100.1, 98.9, 99)]), 0, -1, 100, 2, "S1")[0] == 99.0          # a short books below


def test_stop_is_checked_before_any_profit_exit_within_a_bar():
    assert w(bars([(100, 100.2, 97.9, 98)]), 0, 1, 100, 2, "S1")[:2] == (98.0, "stop|mfe=0.10")
    assert w(bars([(100, 101.5, 97.5, 100)]), 0, 1, 100, 2, "S1")[0] == 98.0          # touches both: stop


def test_s5_has_no_stop_and_sells_at_entry_once_recovered():
    rec = bars([(100, 100.2, 97, 97.5), (97.5, 99, 96, 98), (98, 100.3, 97.9, 100.1)])
    assert w(rec, 0, 1, 100, 2, "S5")[:1] == (100.0,)                                  # dipped again in that bar
    assert w(rec, 0, 1, 100, 2, "S1")[0] == 98.0
    never = bars([(100, 100.2, 97, 97.5), (97.5, 99, 96, 98)], t0=15 * 60 + 9)
    assert w(never, 0, 1, 100, 2, "S5")[0] == 98.0                                     # held to 15:15


def test_trail_time_book_and_live_reference():
    tr = bars([(100, 101, 99.9, 101), (101, 103, 100.8, 102.8), (102.8, 102.9, 101.4, 101.5)])
    assert w(tr, 0, 1, 100, 2, "S3")[:1] == (101.5,)                                   # best +3 -> stop 101.5
    tm = bars([(100, 100.3, 99.5, 99.9)] + [(99.9, 100.2, 99.6, 99.8)] * 10 + [(99.8, 100.3, 99.7, 100.2)])
    assert w(tm, 0, 1, 100, 2, "S4")[:2] == (100.2, "time_book|mfe=0.15")
    lv = bars([(100, 102.2, 99.9, 102), (102, 104.1, 101.9, 104), (104, 104.2, 99.5, 100)])
    assert w(lv, 0, 1, 100, 2, "LIVE")[0] == pytest.approx(0.4 * 102 + 0.3 * 104 + 0.3 * 100)
    assert w(bars([(100, 100.4, 99.5, 100.2)], t0=15 * 60 + 12), 0, 1, 100, 2, "S1")[0] == 100.2   # 15:15 close


def test_smart_exit2_tight_stop_walker():
    from tools.smart_exit2 import walk_tight as t
    assert t(bars([(100, 101.1, 99.8, 101)]), 0, 1, 100, 2, 0.5, 0.25, None)[:2] == (101.0, "book")
    assert t(bars([(100, 100.2, 99.4, 99.6)]), 0, 1, 100, 2, 0.5, 0.25, None)[:2] == (99.5, "stop")
    assert t(bars([(100, 101.2, 99.4, 100)]), 0, 1, 100, 2, 0.5, 0.25, None)[:2] == (99.5, "stop|both")
    assert t(bars([(100, 100.6, 99.9, 100.5), (100.5, 100.6, 99.9, 100)]), 0, 1, 100, 2, 0.5, 0.25, 0.25)[:2] == \
        (100.0, "scratch")
    assert t(bars([(100, 100.1, 98.9, 99.3)]), 0, -1, 100, 2, 0.5, 0.25, None)[:2] == (99.0, "book")
