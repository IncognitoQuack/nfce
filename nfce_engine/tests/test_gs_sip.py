"""gs/features.py and gs/alpha_sip.py (GS-SIP-1) on synthetic stocks: causal features, top-20 selection before
breakouts, the 09:30 trigger window, passive vs marketable entries, stops, the 15:15 exit, caps, every missed fill
kept, and deterministic replay."""
import sys
from datetime import date, datetime, time, timedelta
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import alpha_sip as sip  # noqa: E402
from gs import calendar as cal  # noqa: E402
from gs import execution as ex  # noqa: E402
from gs import features as ft  # noqa: E402

DAY = date(2026, 10, 27)
IST = cal.IST


def at(hh, mm, ss=0, d=DAY):
    return datetime(d.year, d.month, d.day, hh, mm, ss, tzinfo=IST)


def history(price=1000.0, rng=20.0, n=40, day=DAY):
    out, x = [], day
    for _ in range(n):
        x = cal.prev_session(x)
        out.append(ft.DailyBar(x, price, price + rng / 2, price - rng / 2, price))
    return sorted(out, key=lambda b: b.day)


def windows(vol=10_000.0, day=DAY, n=14):
    out, x = [], day
    for _ in range(n):
        x = cal.prev_session(x)
        out.append((x, vol))
    return out


def bar(inst, hh, mm, o, h, l, c, v=1000.0, delay=1):
    s = at(hh, mm)
    return ft.Bar(inst, s, 3, o, h, l, c, v, s + timedelta(minutes=3, seconds=delay))


def book(hh, mm, ss, bid, ask, q=5000, last=None, vol=None):
    return ex.Book(at(hh, mm, ss), ((bid, q),), ((ask, q),), last, vol)


# ---------------------------------------------------------------- features
def test_atr_uses_only_completed_previous_sessions():
    h = history(rng=20.0)
    a, av = ft.atr14_wilder(h, at(9, 21))
    assert a == pytest.approx(20.0) and av <= at(9, 21)
    assert ft.atr14_wilder(h[:-1], at(9, 21)) == (None, None)            # yesterday's bar missing: not available
    late = h[:-1] + [ft.DailyBar(h[-1].day, 1000, 1010, 990, 1000, available_at=at(9, 25))]
    with pytest.raises(ValueError):
        ft.atr14_wilder(late, at(9, 21))                                 # a bar that arrives later cannot be used


def test_opening_window_needs_both_bars_by_the_decision():
    bs = [bar("A", 9, 15, 100, 101, 99.5, 100.5, 600), bar("A", 9, 18, 100.5, 101.2, 100.2, 101, 400)]
    ow, av = ft.opening_window(bs, DAY, at(9, 21, 5))
    assert ow == {"open": 100, "high": 101.2, "low": 99.5, "close": 101, "volume": 1000} and av == at(9, 21, 1)
    assert ft.opening_window(bs, DAY, at(9, 21, 0))[0] is None           # the 09:18 bar is not in yet
    with pytest.raises(ValueError):
        ft.Bar("A", at(9, 18), 3, 1, 1, 1, 1, 1, at(9, 20))              # available before it closes


def test_rvol_needs_all_14_previous_sessions():
    w = windows(500.0)
    assert ft.rvol(1000.0, w, DAY) == pytest.approx(2.0)
    assert ft.rvol(1000.0, w[1:], DAY) is None
    assert ft.rvol(1000.0, [(d, 0.0) if i == 3 else (d, v) for i, (d, v) in enumerate(w)], DAY) is None


def test_er20_vix_imbalance_and_the_asof_guard():
    assert ft.er20([float(i) for i in range(21)]) == pytest.approx(1.0) and ft.er_label(1.0) == "trend"
    assert ft.er20([0.0, 1.0] * 11) == 0.0 and ft.er_label(0.0) == "chop" and ft.er_label(0.45) == "neutral"
    v = [ft.DailyBar(d, 15, 15, 15, 15 + i) for i, d in enumerate(cal.sessions(date(2026, 10, 15), date(2026, 10, 26)))]
    (vix, rise), _ = ft.vix_state(v, at(9, 21))
    assert vix == v[-1].close and rise == pytest.approx(v[-1].close / v[-6].close - 1)
    assert ft.book_imbalance(ex.Book(at(9, 30), ((99, 300), (98, 100)), ((101, 100),))) == pytest.approx(0.6)
    with pytest.raises(ValueError):
        ft.features_asof(at(9, 21), {"x": (1.0, at(9, 22))})


# ---------------------------------------------------------------- selection and triggers
def cand(i, rvol, atr=20.0, pc=1000.0, o=1000.0, c=1005.0):
    return {"instrument_id": i, "rvol": rvol, "atr": atr, "prev_close": pc, "open": o, "close": c,
            "high": 1006.0, "low": 998.0}


def test_selection_top20_by_rvol_with_filters_and_ties():
    cs = [cand(f"S{i:02d}", 1.0 + i / 10) for i in range(25)]
    cs += [cand("LOWATR", 9.0, atr=5.0), cand("LOWRV", 0.9), cand("FLAT", 8.0, c=1000.0), cand("TIEB", 3.45),
           cand("TIEA", 3.45)]
    sel = sip.select(cs, sip.SipConfig())
    ids = [s["instrument_id"] for s in sel]
    assert "LOWATR" not in ids and "LOWRV" not in ids
    assert "FLAT" not in ids                                             # in the top 20 but direction 0: skipped
    assert len(ids) == 19 and ids.index("TIEA") < ids.index("TIEB")
    assert all(s["boundary"] == (1006.0 if s["side"] > 0 else 998.0) for s in sel)


def test_trigger_window_starts_at_0930_and_ends_by_1130():
    s = {"side": 1, "boundary": 101.0}
    cfg = sip.SipConfig()
    assert not sip.triggers(bar("A", 9, 27, 101, 102, 101, 101.5), s, cfg)        # starts before 09:30
    assert sip.triggers(bar("A", 9, 30, 101, 102, 101, 101.5), s, cfg)
    assert not sip.triggers(bar("A", 9, 30, 101, 102, 100, 101.0), s, cfg)        # close AT the boundary
    assert sip.triggers(bar("A", 11, 27, 101, 102, 101, 101.5), s, cfg)
    assert not sip.triggers(bar("A", 11, 30, 101, 102, 101, 101.5), s, cfg)       # closes after 11:30
    assert sip.triggers(bar("A", 10, 0, 99, 99, 97, 97.5), {"side": -1, "boundary": 98.0}, cfg)


# ---------------------------------------------------------------- the engine
def universe(n=1, price=1000.0):
    return {f"S{i}": sip.StockDay(f"S{i}", history(price), windows(500.0), sector=f"sec{i}") for i in range(n)}


def opening(inst, up=True, vol=1000.0):
    if up:
        return [bar(inst, 9, 15, 1000, 1004, 999, 1003, vol / 2), bar(inst, 9, 18, 1003, 1006, 1002, 1005, vol / 2)]
    return [bar(inst, 9, 15, 1000, 1001, 996, 997, vol / 2), bar(inst, 9, 18, 997, 998, 994, 995, vol / 2)]


def run(events, cfg=sip.SipConfig(), uni=None):
    e = sip.SipEngine(cfg)
    e.start_day(DAY, uni or universe(), (15.0, 0.02))
    for x in sorted(events, key=lambda x: (x[0], x[1])):
        t, kind, obj = x[0], x[1], x[2]
        if kind == "bar":
            e.on_bar(obj)
        else:
            e.on_book(x[3], obj)
    e.on_clock(at(15, 31))
    return e, e.end_day()


def ev_bars(bs):
    return [(b.available_at, "bar", b) for b in bs]


def ev_books(inst, bks):
    return [(b.ts, "book", b, inst) for b in bks]


def trade_day(inst="S0", through=True, stop=False):
    bars = opening(inst) + [bar(inst, 9, 30, 1005, 1008, 1004, 1007)]                 # closes above 1006 at 09:33
    bks = [book(9, 29, 0, 1004.5, 1005.0, vol=0, last=1005)]
    bks += [book(9, 30 + i, 0, 1005.0, 1005.5, vol=1000 * (i + 1) * 100, last=1005) for i in range(3)]
    bks += [book(9, 33, 2, 1006.9, 1007.1, vol=400_000, last=1007)]                  # decision book: bid 1006.9
    bks += [book(9, 33, 5, 1007.0, 1007.2, vol=410_000, last=1007)]                  # after the 2 s latency
    if through:
        bks += [book(9, 34, 0, 1005.5, 1005.9, q=20_000, vol=500_000, last=1005.8)]  # ask 1005.9 < limit 1006 - tick
    else:
        bks += [book(9, 34, 0, 1007.5, 1008.0, vol=500_000, last=1008)]
    if stop:
        bks += [book(10, 0, 0, 994.0, 994.5, vol=600_000), book(10, 1, 0, 993.0, 993.5, vol=650_000)]
    bks += [book(15, 15, 1, 1015.0, 1015.5, vol=900_000)]
    return ev_bars(bars) + ev_books(inst, bks)


def test_passive_strict_fill_at_the_limit_then_out_at_1515():
    e, r = run(trade_day())
    o = r["opportunities"][0]
    assert r["selected"] == ["S0"] and o["status"] == "closed"
    assert o["limit"] == 1006.0 and o["entry"] == 1006.0                             # min(boundary 1006, bid 1006.9)
    assert o["exit"] == 1015.0 and o["exit_reason"] == "time 15:15"
    assert o["net"] == pytest.approx((1015.0 - 1006.0) * o["qty"] - o["fees"])
    assert 0 < o["qty"] * 1006.0 <= 100_000 and r["net"] == pytest.approx(o["net"])
    # x1.5 spread: the 15:15 exit sold 0.25 below the mid; widened costs another 0.125 a share
    assert o["net_widened"] == pytest.approx(o["net"] - 0.125 * o["qty"]) and r["net_widened"] == o["net_widened"]
    it = e.intents[0]
    assert it.activate_at == it.decided_at + timedelta(seconds=2)
    assert it.expires_at == it.decided_at + timedelta(seconds=180)


def test_unfilled_opportunity_scores_zero_and_is_kept():
    e, r = run(trade_day(through=False))
    o = r["opportunities"][0]
    assert o["status"] == "unfilled" and o["net"] == 0.0 and r["net"] == 0.0
    assert any(x.kind == "expire" for x in e.execs)


def test_branch_m_enters_at_the_ask_and_reports_the_missed_winner():
    _, rp = run(trade_day(through=False))
    _, rm = run(trade_day(through=False), sip.SipConfig(branch="M", scenario="market"))
    om = rm["opportunities"][0]
    assert om["status"] == "closed" and om["entry"] == pytest.approx(1007.2) and om["net"] > 0     # the first ask after 2 s
    assert rp["opportunities"][0]["net"] == 0.0                                     # passive missed this winner


def test_stop_exits_at_the_next_book_after_the_latency():
    e, r = run(trade_day(stop=True))
    o = r["opportunities"][0]
    stop = 1006.0 - 0.5 * 20.0
    assert o["exit_reason"] == "stop" and o["exit"] == 993.0                        # the 10:01 bid, not 994
    assert o["net"] == pytest.approx((993.0 - 1006.0) * o["qty"] - o["fees"]) and 994.0 < stop + 1


def test_late_opening_bar_makes_the_stock_ineligible():
    bars = opening("S0")
    bars[1] = ft.Bar("S0", at(9, 18), 3, 1003, 1006, 1002, 1005, 500, at(9, 21, 30))   # arrives after selection
    e, r = run(ev_bars(bars + [bar("S0", 9, 30, 1005, 1008, 1004, 1007)]) +
               ev_books("S0", [book(9, 33, 2, 1006.9, 1007.1)]))
    assert r["selected"] == [] and r["opportunities"] == []


def test_no_book_refresh_means_skipped_not_dropped():
    bars = opening("S0") + [bar("S0", 9, 30, 1005, 1008, 1004, 1007)]
    e, r = run(ev_bars(bars) + ev_books("S0", [book(9, 40, 0, 1006.9, 1007.1)]))
    o = r["opportunities"][0]
    assert o["status"] == "skipped" and "no book refresh in time" in o["reasons"] and o["net"] == 0.0


def test_at_most_four_open_positions():
    uni = universe(6)
    evs = []
    for i in range(6):
        evs += [x if x[1] == "bar" else (x[0], x[1], x[2], f"S{i}") for x in trade_day(f"S{i}")]
    e, r = run(evs, uni=uni)
    filled = [o for o in r["opportunities"] if o["qty"] > 0]
    skipped = [o for o in r["opportunities"] if o["status"] == "skipped"]
    assert len(filled) <= 4 and len(skipped) >= 2
    assert any("max open positions" in rr or "cap" in rr for o in skipped for rr in o["reasons"])


def test_high_vix_quarter_size_and_unknown_vix_skips():
    e = sip.SipEngine()
    e.start_day(DAY, universe(), (26.0, 0.0))
    full, _ = run(trade_day())
    for x in sorted(trade_day(), key=lambda x: (x[0], x[1])):
        e.on_bar(x[2]) if x[1] == "bar" else e.on_book(x[3], x[2])
    q_quarter = e.end_day()["opportunities"][0]["qty_req"]
    assert 0 < q_quarter < full.end_day()["opportunities"][0]["qty_req"]
    e2 = sip.SipEngine()
    e2.start_day(DAY, universe(), (None, None))
    for x in sorted(trade_day(), key=lambda x: (x[0], x[1])):
        e2.on_bar(x[2]) if x[1] == "bar" else e2.on_book(x[3], x[2])
    assert e2.end_day()["opportunities"][0]["status"] == "skipped"


def test_replay_is_deterministic():
    a, _ = run(trade_day(stop=True))
    b, _ = run(trade_day(stop=True))
    assert a.fingerprint() == b.fingerprint() and len(a.execs) >= 2


def test_replay_bars_from_snapshots_are_known_only_after_they_close():
    from tools import gs_replay as rp
    bks = [ex.Book(at(9, 14, 18), ((99, 1),), ((100, 1),), 100.0, 1000.0)]
    bks += [ex.Book(at(9, 15 + i, 18), ((99, 1),), ((100, 1),), 100.0 + i, 1000.0 + 500 * (i + 1)) for i in range(6)]
    bars = rp.bars_from_books("S0", bks, DAY)
    assert bars[0].start == at(9, 15) and bars[0].available_at == at(9, 18, 18)
    assert (bars[0].open, bars[0].high, bars[0].close, bars[0].volume) == (100.0, 102.0, 102.0, 1500.0)
    assert len(bars) == 1                                                # the 09:18 bar has no later snapshot yet
    txt = rp.report([])
    assert "EXPLORATORY" in txt and "NOT evidence" in txt


def test_open_position_without_an_exit_quote_is_unresolved_with_bounds():
    evs = [x for x in trade_day() if not (x[1] == "book" and x[2].ts.hour == 15)]   # no quote after 15:15
    e, r = run(evs)
    o = r["opportunities"][0]
    assert o["net"] is None and o["status"] == "positioned" and len(r["unresolved"]) == 1
    _, worst, best = r["unresolved"][0]
    assert worst < best and r["net_worst"] == pytest.approx(worst) and r["net_best"] == pytest.approx(best)



def test_rbi_window_and_budget_day_block_entries(monkeypatch):
    monkeypatch.setattr(cal, "EVENTS", ((DAY, "rbi"),))
    e, r = run(trade_day())
    o = r["opportunities"][0]
    assert o["status"] == "skipped" and o["reasons"] == ["event window: RBI policy"]
    monkeypatch.setattr(cal, "EVENTS", ((DAY, "budget"),))
    e, r = run(trade_day())
    assert r["opportunities"][0]["reasons"] == ["event day: Union Budget"]
