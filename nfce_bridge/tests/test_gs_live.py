"""GS wired into the bridge (bridge/gs_live.py): off by default, fed from the stock engine's data, one batched depth
request, isolated from the bridge, /gs and /toggle gs. No network, no real data (daily dir and GS db are tmp)."""
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from bridge.providers import IST, ProviderError
from conftest import FakeTelegram, StubProvider, make_payload

DAY = datetime(2026, 10, 21, tzinfo=IST).date()          # a Wednesday


def at(hh, mm, ss=0):
    return datetime(2026, 10, 21, hh, mm, ss, tzinfo=IST)


class DepthProvider(StubProvider):
    """StubProvider plus the raw 5-level quote endpoint GS uses; `book(now)` scripts bid/ask."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.depth_calls, self.fail_depth = [], None
        self.book = lambda now: (1006.9, 1007.1)

    def _get(self, path, params):
        if self.fail_depth:
            raise self.fail_depth
        assert path == "/market-quote/quotes"
        self.depth_calls.append(params["instrument_key"])
        bid, ask = self.book(self.clock())
        return {"data": {"NSE_EQ:AAA": {"instrument_token": "NSE_EQ|AAA", "last_price": (bid + ask) / 2,
                                        "volume": 10_000 * len(self.depth_calls),
                                        "depth": {"buy": [{"price": bid, "quantity": 20_000}],
                                                  "sell": [{"price": ask, "quantity": 20_000}]}}}}


def hist_3m(n_sessions=25):
    days, x = [], DAY
    from gs import calendar as cal
    for _ in range(n_sessions):
        x = cal.prev_session(x)
        days.append(x)
    idx = []
    for d in sorted(days):
        idx += list(pd.date_range(f"{d} 09:15", periods=125, freq="3min", tz=IST))
    v = np.full(len(idx), 500.0)
    return pd.DataFrame({"open": 1000.0, "high": 1010.0, "low": 990.0, "close": 1000.0, "volume": v, "oi": 0.0},
                        index=pd.DatetimeIndex(idx))


def minute(t, o, h, l, c, v=750):
    return int(t.timestamp() * 1000), [o, h, l, c, v]


@pytest.fixture
def gsb(settings, clock, tmp_path):
    from bridge.service import Bridge
    from bridge.store import Store
    settings.gs, settings.stock_engine, settings.option_legs = True, True, False
    settings.gs_db = tmp_path / "gs.db"
    clock.set(at(9, 0))
    prov = DepthProvider(make_payload(), clock=clock)
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    (tmp_path / "daily").mkdir()
    b.gs.daily_dir = tmp_path / "daily"                  # empty: daily bars come from the 3m history
    st = b.stocks
    st.universe = [{"symbol": "AAA", "equity_key": "NSE_EQ|AAA", "fut_key": "NSE_FO|FAAA", "lot": 500, "tick": 0.05}]
    st.hist = {"AAA": hist_3m(), "INDIAVIX": hist_3m().assign(open=15.0, high=15.0, low=15.0, close=15.0)}
    st.day = DAY
    mins = dict([minute(at(9, 15), 1000, 1003, 999, 1002), minute(at(9, 16), 1002, 1004, 1001, 1003),
                 minute(at(9, 17), 1003, 1004, 1002, 1003), minute(at(9, 18), 1003, 1006, 1003, 1005),
                 minute(at(9, 19), 1005, 1005, 1004, 1004), minute(at(9, 20), 1004, 1006, 1004, 1005)])
    st.minutes = {"AAA": mins}
    yield b, prov, clock
    b.gs.stop()


def run_to(b, clock, t):
    clock.set(t)
    b.gs.step(t)


def test_gs_is_off_by_default(make_bridge):
    b, _, _ = make_bridge()
    assert b.gs is None and "off" in b.handle_command("/gs")


def test_a_morning_select_trigger_decide_fill_and_close(gsb):
    b, prov, clock = gsb
    run_to(b, clock, at(9, 0))
    assert b.gs.day == DAY and "1 stocks" in b.gs.status
    run_to(b, clock, at(9, 21, 20))                       # both opening bars fed (seen at 09:21:20)
    run_to(b, clock, at(9, 21, 35))                       # selection after the 30 s grace
    eng = b.gs.adapter.engines[0]
    assert list(eng.selected) == ["NSE_EQ|AAA"] and eng.selected["NSE_EQ|AAA"]["boundary"] == 1006
    st = b.stocks.minutes["AAA"]
    for k, c in enumerate((1006.5, 1007.0, 1007.5)):
        t, row = minute(at(9, 30 + k), c - 0.5, c + 0.5, c - 0.6, c)
        st[t] = row
    t = at(9, 21, 45)
    while t < at(9, 33, 20):                              # the 2 s thread; quotes every 10 s build trailing volume
        run_to(b, clock, t)
        t += timedelta(seconds=10)
    run_to(b, clock, at(9, 33, 20))                       # the 09:30 bar closes above 1006 -> decision on a fresh book
    o = eng.opps["NSE_EQ|AAA"]
    assert o.status == "resting" and o.limit == 1006.0          # min(boundary 1006, bid 1006.9)
    m = b.gs.adapter.engines[2].opps["NSE_EQ|AAA"]
    assert m.qty > 0 and m.entry_avg == pytest.approx(1007.1)   # branch M: the ask, after the 2 s latency
    assert 0 < (m.fills[0].ts - m.activate_at).total_seconds() <= 10
    prov.book = lambda now: (1005.5, 1005.9)              # a later quote trades through the limit
    run_to(b, clock, at(9, 33, 24))
    assert o.qty > 0 and o.entry_avg == 1006.0
    prov.book = lambda now: (1015.0, 1015.5)
    run_to(b, clock, at(15, 15, 5))                       # time exit
    run_to(b, clock, at(15, 31, 0))
    assert o.status == "closed" and "closed 2026-10-21" in b.gs.status
    rep = b.handle_command("/gs")
    assert "NOT yet evidence" in rep and "P strict" in rep and "dry run" in rep and b.gs.mode == "DESIGN"
    from gs import store as gstore
    s = gstore.Store(b.s.gs_db)
    assert len(s.intents()) == 3 and s.latest_snapshot("day_equity", "GS-SIP-1/P/strict")["day"] == "2026-10-21"


def test_quote_cadence_is_one_batched_request_every_10_s_and_none_before_0921(gsb):
    b, prov, clock = gsb
    run_to(b, clock, at(9, 0))
    run_to(b, clock, at(9, 21, 20))
    assert prov.depth_calls == []                          # nothing selected yet
    run_to(b, clock, at(9, 21, 35))
    for s in (37, 39, 41, 43, 45, 47):
        run_to(b, clock, at(9, 21, s))
    assert len(prov.depth_calls) == 2 and prov.depth_calls[0] == "NSE_EQ|AAA"     # 09:21:35 and 09:21:45


def test_gs_failures_never_reach_the_bridge(gsb, monkeypatch):
    b, prov, clock = gsb
    run_to(b, clock, at(9, 0))
    prov.fail_depth = ProviderError("Upstox HTTP 429")
    run_to(b, clock, at(9, 21, 20))
    run_to(b, clock, at(9, 21, 35))
    assert "quote request failed" in b.gs.status
    monkeypatch.setattr(b.gs.adapter.engines[0], "on_clock", lambda now: 1 / 0)
    run_to(b, clock, at(9, 22, 0))                         # an engine error disables GS for the day, quietly
    assert not b.gs.adapter.healthy
    calls = []
    monkeypatch.setattr(b.gs, "ensure_thread", lambda: calls.append(1) or 1 / 0)
    b.tick()                                               # the bridge tick survives a GS glue failure
    assert calls == [1] and b.health_status()["gs"]


def test_toggle_gs_off_stops_feeding(gsb):
    b, prov, clock = gsb
    b.store.kv_set("feature_off_gs", True)
    run_to(b, clock, at(9, 0))
    assert b.gs.day is None and "switched off" in b.gs.status


def test_a_late_start_sits_the_day_out(gsb):
    b, prov, clock = gsb
    run_to(b, clock, at(10, 5))                            # the bridge restarted mid-morning
    assert "late start" in b.gs.status
    run_to(b, clock, at(10, 5, 10))
    assert b.gs.adapter.engines[0].selected == {}



def test_a_frozen_manifest_runs_and_a_changed_one_sits_the_day_out(gsb, monkeypatch):
    b, prov, clock = gsb
    from bridge import gs_live
    from tools import gs_manifest
    from gs import registry as reg
    m = gs_manifest.build(start="2026-10-21", status="FROZEN")
    reg.freeze(b.gs.adapter.store, m, at(8, 0))
    assert gs_live.frozen_check(b.gs.adapter.store)[0] == "FROZEN"
    run_to(b, clock, at(9, 0))
    assert b.gs.mode == "FROZEN" and "count toward its pilot" in b.handle_command("/gs")
    real = gs_manifest.build
    monkeypatch.setattr(gs_manifest, "build", lambda **k: {**real(**k), "code_hashes": {**real(**k)["code_hashes"],
                                                                                       "nfce_engine/gs/risk.py": "x"}})
    b.gs.day = None
    run_to(b, clock, at(9, 0, 5))
    assert b.gs.mode == "MISMATCH" and "NOT RUN today" in b.gs.status and "gs/risk.py" in b.gs.status
    run_to(b, clock, at(9, 21, 40))
    assert b.gs.adapter.engines[0].selected == {} or b.gs.closed_day == b.gs.day


def test_a_registered_calendar_extension_keeps_the_freeze(gsb, monkeypatch):
    b, prov, clock = gsb
    from bridge import gs_live
    from tools import gs_manifest
    from gs import registry as reg
    reg.freeze(b.gs.adapter.store, gs_manifest.build(start="2026-10-21", status="FROZEN"), at(8, 0))
    real = gs_manifest.build

    def extended(**k):
        m = real(**k)
        return {**m, "calendar_sha256": "c2027", "code_hashes": {**m["code_hashes"], gs_manifest.CALENDAR: "c2027"}}
    monkeypatch.setattr(gs_manifest, "build", extended)
    assert gs_live.frozen_check(b.gs.adapter.store)[0] == "MISMATCH"             # not registered yet
    reg.register_calendar_extension(b.gs.adapter.store, "GS-SIP-1", "c2027", "2027-12-31", at(8, 1), "NSE 2027 list")
    assert gs_live.frozen_check(b.gs.adapter.store)[0] == "FROZEN"
    monkeypatch.setattr(gs_manifest, "build", lambda **k: {**extended(**k), "protocol_sha256": "edited"})
    assert gs_live.frozen_check(b.gs.adapter.store)[0] == "MISMATCH"             # the protocol may never change
