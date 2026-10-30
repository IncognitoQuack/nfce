"""The 'guarded' account (evidence/guarded_account_protocol.md): base + 30-min time stop + 15% cost gate + no index entry
without a fresh futures quote. Risk controls only; these tests check the rules, not any profit."""
from datetime import timedelta

from test_account import LV, T, acct, leg, mk  # noqa: F401  (acct is a fixture)


def test_guarded_skips_an_index_entry_without_a_fresh_futures_quote(acct):  # noqa: F811
    g, _ = mk(acct, "guarded", "G20")
    g.b.fresh_quotes = lambda root: (None, object())                      # 28 Oct 13:48: SENSEX futures stale
    assert "no fresh SENSEX futures quote" in g.consider(T, "s1", leg(und="SENSEX"), "SPOT", 1, LV, 0.0, "x")
    assert not g.positions
    g.b.fresh_quotes = lambda root: (object(), object())
    assert "bought" in g.consider(T, "s2", leg(und="SENSEX"), "SPOT", 1, LV, 0.0, "x")
    assert "bought" in g.consider(T, "s3", leg(und="TCS", key="O3"), "SPOT", 1, LV, 0.0, "x")   # stocks: no check
    b, _ = mk(acct, "base", "B2")
    b.b.fresh_quotes = lambda root: (None, None)
    assert "bought" in b.consider(T, "s4", leg(und="NIFTY", key="O4"), "SPOT", 1, LV, 0.0, "x")  # base unchanged


def test_guarded_cost_gate_is_15_percent(acct):  # noqa: F811
    g, _ = mk(acct, "guarded", "G20")
    assert g.max_cost_share == 0.15
    b, _ = mk(acct, "base", "B2")
    assert b.max_cost_share == 0.25


def test_guarded_has_the_30_minute_time_stop_but_not_the_cluster_cap(acct):  # noqa: F811
    g, prov = mk(acct, "guarded", "G20")
    g.b.fresh_quotes = lambda root: (object(), object())
    g.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x")
    g.consider(T + timedelta(minutes=5), "s2", leg(und="TCS", key="O2"), "SPOT", 1, LV, 0.0, "x")
    assert "bought" in g.consider(T + timedelta(minutes=10), "s3", leg(und="INFY", key="O3"), "SPOT", 1, LV, 0.0, "x")
    prov.q = {"OPT": (58, 57.0, 58.0), "O2": (61, 60.0, 61.0), "O3": (60, 59.0, 60.0), "SPOT": (23100, None, None)}
    g.on_tick(T + timedelta(minutes=30))
    assert "s1" not in g.positions and "s2" in g.positions
    last = g.store.db.execute("SELECT reason FROM account_fills WHERE acct='G20' ORDER BY id DESC LIMIT 1").fetchone()
    assert last[0] == "30-minute time stop"
