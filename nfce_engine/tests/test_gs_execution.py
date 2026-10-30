"""gs/execution.py and gs/budget.py: latency, crossed quotes, depth exhaustion, capacity, passive scenarios,
markouts, the wings-first state machine and the shared request budget. Synthetic books only."""
import multiprocessing as mp
import random
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import budget as bg  # noqa: E402
from gs import execution as ex  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
T = datetime(2026, 10, 27, 9, 33, tzinfo=IST)
NOFEE = lambda side, px, q, ts: 0.0  # noqa: E731


def bk(sec, bid, ask, bq=1000, aq=1000, depth=None, last=None, vol=None):
    bids = depth[0] if depth else ((bid, bq),)
    asks = depth[1] if depth else ((ask, aq),)
    return ex.Book(T + timedelta(seconds=sec), bids, asks, last, vol)


# ---------------------------------------------------------------- books and walking
def test_validity_rejects_crossed_one_sided_and_empty_quotes():
    assert bk(0, 100.0, 100.1).valid and bk(0, 100.0, 100.0).valid
    assert not bk(0, 100.2, 100.1).valid and not bk(0, 0.0, 100.1).valid and not bk(0, 100.0, 100.1, aq=0).valid
    b = ex.Book.from_depth(T, {"buy": [{"price": 99.9, "quantity": 10}, {"price": 0, "quantity": 0}],
                               "sell": [{"price": 100.1, "quantity": 5}]})
    assert b.bids == ((99.9, 10.0),) and b.mid == pytest.approx(100.0)


def test_walk_uses_levels_in_order_and_never_extrapolates():
    b = bk(0, 0, 0, depth=(((99.9, 100),), ((100.0, 100), (100.1, 100), (100.2, 100))))
    w = ex.walk(b, 1, 250)
    assert w.qty == 250 and w.avg_price == pytest.approx((100 * 100 + 100 * 100.1 + 50 * 100.2) / 250)
    assert w.impact_bp == pytest.approx((w.avg_price - 100.0) / 100.0 * 1e4)
    x = ex.walk(b, 1, 400)
    assert x.exhausted and x.qty == 300                                  # depth ran out: no imaginary 6th level
    assert ex.walk(b, 1, 250, limit=100.05).qty == 100


def test_impact_cap_reduces_size_in_lots():
    b = bk(0, 0, 0, depth=(((99.9, 100),), ((100.0, 100), (100.1, 100), (100.5, 1000))))
    assert ex.max_qty_within_impact(b, 1, 300) == 142                    # 142 @ 100.0296 = 2.96 bp; 143 > 3 bp
    w = ex.walk(b, 1, ex.max_qty_within_impact(b, 1, 300))
    assert w.impact_bp <= 3.0
    assert ex.max_qty_within_impact(b, 1, 300, lot=65) == 130


def test_capacity_is_five_percent_of_trailing_traded_value_per_minute():
    books = [ex.Book(T + timedelta(minutes=i), ((99.9, 1),), ((100.0, 1),), 100.0, 10_000.0 * i) for i in range(7)]
    # 10,000 shares a minute at Rs 100 = Rs 10 L a minute -> 5% = Rs 50,000 = 500 shares
    assert ex.capacity_qty(100.0, books, books[-1].ts) == pytest.approx(500.0)
    reset = books[:3] + [ex.Book(books[3].ts, ((99.9, 1),), ((100.0, 1),), 100.0, 5.0)]
    assert ex.traded_value_per_min(reset) == pytest.approx([1e6, 1e6])   # a volume reset gives no value
    assert ex.capacity_qty(100.0, [], T) == 0.0


# ---------------------------------------------------------------- marketable fills and latency
def test_market_fill_waits_for_latency_and_skips_invalid_books():
    books = [bk(0, 100.0, 100.1), bk(1, 100.3, 100.2), bk(3, 100.0, 100.2)]
    e = ex.market_fill("i", 0, "X", 1, 50, books, T + timedelta(seconds=2), NOFEE)
    assert e.kind == "fill" and e.ts == books[2].ts and e.price == 100.2    # not the pre-latency or crossed book


def test_market_fill_expires_without_a_timely_quote_and_rejects_thin_books():
    e = ex.market_fill("i", 0, "X", 1, 50, [bk(30, 100.0, 100.1)], T + timedelta(seconds=2), NOFEE)
    assert e.kind == "expire"
    thin = [bk(3, 100.0, 100.1, depth=(((100.0, 10),), ((100.1, 10), (101.0, 10))))]
    r = ex.market_fill("i", 0, "X", 1, 50, thin, T, NOFEE, lot=50)
    assert r.kind == "reject"
    p = ex.market_fill("i", 0, "X", 1, 50, thin, T, NOFEE)
    assert p.kind == "fill" and p.qty == 10 and dict(p.meta)["partial"]


# ---------------------------------------------------------------- passive scenarios
def test_passive_limit_rests_at_the_boundary_or_the_touch():
    b = bk(0, 100.0, 100.1)
    assert ex.passive_limit(1, 100.5, b) == 100.0 and ex.passive_limit(1, 99.8, b) == 99.8
    assert ex.passive_limit(-1, 99.5, b) == 100.1 and ex.passive_limit(-1, 100.4, b) == 100.4


def test_strict_needs_a_trade_through_with_size_and_fills_at_the_limit():
    books = [bk(2, 99.95, 100.05), bk(60, 99.9, 100.0, aq=5000), bk(120, 99.85, 99.95, aq=300),
             bk(150, 99.80, 99.90, aq=5000)]
    f = ex.passive_fill("i", 0, "X", 1, 600, 100.0, 0.05, books, T + timedelta(seconds=2), T + timedelta(seconds=180),
                        NOFEE, "strict")
    fills = [e for e in f if e.kind == "fill"]
    # 60 s: ask AT the limit is a touch, not a trade-through; 120 s: through, 10% of 300 = 30; 150 s: 10% of 5000 = 500
    assert [e.qty for e in fills] == [30, 500] and all(e.price == 100.0 for e in fills)
    assert f[-1].kind == "expire" and f[-1].qty == 70


def test_touch_is_optimistic_and_expiry_is_respected():
    books = [bk(2, 99.95, 100.05), bk(60, 99.9, 100.0)]
    t = ex.passive_fill("i", 0, "X", 1, 600, 100.0, 0.05, books, T + timedelta(seconds=2), T + timedelta(seconds=180),
                        NOFEE, "touch")
    assert t[0].kind == "fill" and t[0].qty == 600
    late = ex.passive_fill("i", 0, "X", 1, 600, 100.0, 0.05, [bk(200, 99.0, 99.5, aq=10**6)],
                           T + timedelta(seconds=2), T + timedelta(seconds=180), NOFEE, "strict")
    assert [e.kind for e in late] == ["expire"]


def test_a_limit_crossing_on_arrival_is_marketable():
    books = [bk(2, 99.7, 99.8, aq=1000)]                                   # the ask fell below the buy limit
    f = ex.passive_fill("i", 0, "X", 1, 100, 100.0, 0.05, books, T + timedelta(seconds=2), T + timedelta(seconds=180),
                        NOFEE, "strict")
    assert f[0].kind == "fill" and f[0].price == 99.8 and f[0].reason == "marketable on arrival"


def test_short_side_strict_through():
    books = [bk(2, 100.0, 100.1), bk(60, 100.15, 100.25, bq=2000)]
    f = ex.passive_fill("i", 0, "X", -1, 100, 100.1, 0.05, books, T + timedelta(seconds=2), T + timedelta(seconds=180),
                        NOFEE, "strict")
    assert f[0].kind == "fill" and f[0].price == 100.1 and f[0].qty == 100


def test_adverse_stress_drops_the_best_quarter_and_charges_2bp():
    out = ex.adverse_stress([100.0, -50.0, None, 30.0, 10.0], [100_000.0] * 5)
    assert out == [0.0, -50.0 - 20.0, 0.0, 30.0 - 20.0, 10.0 - 20.0]       # 4 fills: the best 1 removed


def test_markouts_signed_by_side():
    books = [bk(10, 100.1, 100.3), bk(60, 99.9, 100.1), bk(300, 100.4, 100.6)]
    m = ex.markouts(T, 100.0, 1, books)
    assert m[10] == pytest.approx(20.0) and m[60] == pytest.approx(0.0) and m[300] == pytest.approx(50.0)
    assert ex.markouts(T, 100.0, -1, books)[300] == pytest.approx(-50.0)
    assert ex.markouts(T, 100.0, 1, [])[10] is None


# ---------------------------------------------------------------- structures (wings first)
LEGS = [("CW", 1, 65, "wing"), ("PW", 1, 65, "wing"), ("SC", -1, 65, "short"), ("SP", -1, 65, "short")]


def snap(sec, missing=()):
    q = {"CW": (138.3, 138.85), "PW": (101.2, 101.55), "SC": (287.0, 287.9), "SP": (191.45, 192.2)}
    return (T + timedelta(seconds=sec),
            {k: ex.Book(T + timedelta(seconds=sec), ((b, 650),), ((a, 650),)) for k, (b, a) in q.items()
             if k not in missing})


def test_wings_fill_before_shorts_and_the_credit_is_right():
    st = ex.enter_structure("ovn", LEGS, [snap(2)], T + timedelta(seconds=2), T + timedelta(seconds=60), NOFEE, 65)
    assert st.state == "OPEN" and [e.instrument_id for e in st.events] == ["CW", "PW", "SC", "SP"]
    credit = sum(-e.side * e.price for e in st.events)
    assert credit == pytest.approx(287.0 + 191.45 - 138.85 - 101.55)


def test_missing_wing_means_nothing_is_entered():
    st = ex.enter_structure("ovn", LEGS, [snap(2, missing=("PW",))], T, T + timedelta(seconds=60), NOFEE, 65)
    assert st.state == "CANCELLED" and st.events == []


def test_failed_short_unwinds_the_wings_at_executable_quotes():
    snaps = [snap(2, missing=("SP",)), snap(40, missing=("SP",)), snap(70)]
    st = ex.enter_structure("ovn", LEGS, snaps, T, T + timedelta(seconds=60), NOFEE, 65)
    assert st.state == "UNWOUND"
    buys = [e for e in st.events if e.side > 0]
    sells = [e for e in st.events if e.side < 0]
    assert len(buys) == 2 and len(sells) == 2 and all(e.instrument_id in ("CW", "PW") for e in sells)
    legging = sum(-e.side * e.price for e in st.events) * 65
    assert legging < 0                                                     # paid both spreads: a real loss
    st2 = ex.enter_structure("ovn", LEGS, [snap(2, missing=("SP",))], T, T + timedelta(seconds=60), NOFEE, 65)
    assert st2.state == "RESIDUAL" and len(st2.open_qty) == 2              # no later quote: wings left open


def test_exit_closes_shorts_before_wings_and_leaves_residuals():
    st = ex.enter_structure("ovn", LEGS, [snap(2)], T, T + timedelta(seconds=60), NOFEE, 65)
    later = [snap(1000, missing=("SC", "CW")), snap(1060, missing=("CW",)), snap(1120)]
    st = ex.exit_structure(st, "ovn", later, T + timedelta(seconds=1000), NOFEE, 65)
    exits = st.events[4:]
    order = [(e.instrument_id, e.ts) for e in exits]
    assert st.state == "CLOSED" and order[0][0] == "SP" and order[1][0] == "SC"
    assert all(ts >= order[1][1] for k, ts in order[2:])                   # wings at/after the later short exit
    st3 = ex.enter_structure("ovn", LEGS, [snap(2)], T, T + timedelta(seconds=60), NOFEE, 65)
    st3 = ex.exit_structure(st3, "ovn", [snap(1000, missing=("SC",))], T + timedelta(seconds=1000), NOFEE, 65)
    assert st3.state == "RESIDUAL" and 2 in st3.open_qty and 0 in st3.open_qty   # SC and the wings still open


# ---------------------------------------------------------------- request budget
def test_budget_window_per_second_and_priorities(tmp_path):
    b = bg.RequestBudget(tmp_path / "rb.db", window_max=20, per_second=4,
                         ceiling={0: 20, 1: 20, 2: 18, 3: 15, 4: 12})
    t = 1000.0
    assert all(b.acquire(bg.CHAIN, "chain", now=t) for _ in range(4))
    assert not b.acquire(bg.EXIT, "x", now=t)                             # 4 per second, whatever the class
    for i in range(8):
        assert b.acquire(bg.WARMUP, "w", now=t + 1 + i)
    assert not b.acquire(bg.WARMUP, "w", now=t + 20)                      # warm-up stops at 12
    assert b.acquire(bg.CHAIN, "c", now=t + 21) and b.acquire(bg.ACTIVE, "a", now=t + 22)
    for i in range(5):
        b.acquire(bg.ACTIVE, "a", now=t + 30 + i)
    assert b.used(now=t + 40) == 18 and not b.acquire(bg.ACTIVE, "a", now=t + 41)
    assert b.acquire(bg.EXIT, "x", now=t + 42) and b.acquire(bg.HEALTH, "h", now=t + 43)   # the last tokens
    assert not b.acquire(bg.EXIT, "x", now=t + 44)
    assert b.acquire(bg.WARMUP, "w", n=1, now=t + 1900)                   # the window slid
    assert sum(b.by_priority(now=t + 44).values()) == 20


def _worker(path, n, q):
    b = bg.RequestBudget(path, window_max=50, per_second=1000, ceiling={0: 50, 1: 50, 2: 50, 3: 50, 4: 50})
    q.put(sum(b.acquire(bg.CHAIN, "p", now=5000.0) for _ in range(n)))


def test_budget_is_shared_across_processes(tmp_path):
    path = str(tmp_path / "rb.db")
    bg.RequestBudget(path)
    q = mp.get_context("spawn").Queue()
    ps = [mp.get_context("spawn").Process(target=_worker, args=(path, 30, q)) for _ in range(3)]
    for p in ps:
        p.start()
    for p in ps:
        p.join(30)
    assert sum(q.get() for _ in ps) == 50                                  # 90 asked, exactly the cap granted


def test_http_429_freezes_entries_with_backoff(tmp_path):
    b = bg.RequestBudget(tmp_path / "rb.db")
    w = b.on_429(2, now=100.0, rng=random.Random(1))
    assert 20.0 <= w <= 25.0 and b.entries_frozen(now=100.0 + w - 1) and not b.entries_frozen(now=100.0 + w + 1)
    assert b.on_429(10, now=0.0, rng=random.Random(1)) <= 375.0


def test_partial_fills_of_one_order_pay_brokerage_once():
    fee = lambda side, px, q, ts: 23.6 + 0.001 * px * q                 # noqa: E731  brokerage + GST + the rest
    rest = lambda side, px, q, ts: 0.001 * px * q                       # noqa: E731
    books = [bk(2, 99.95, 100.05), bk(60, 99.9, 99.95, aq=300), bk(120, 99.85, 99.9, aq=300)]
    f = ex.passive_fill("i", 0, "X", 1, 100, 100.0, 0.05, books, T + timedelta(seconds=2), T + timedelta(seconds=180),
                        fee, "strict")
    o = ex.PassiveOrder("i", 0, "X", 1, 100, 100.0, 0.05, T + timedelta(seconds=2), T + timedelta(seconds=180), fee,
                        "strict", fee_fn_rest=rest)
    g = [e for b in books for e in o.on_book(b)]
    assert [e.qty for e in g] == [30, 30] and g[0].fee == pytest.approx(23.6 + 3.0) and g[1].fee == pytest.approx(3.0)
    assert [e.fee for e in f if e.kind == "fill"] == [pytest.approx(26.6), pytest.approx(26.6)]   # without the rest fn
