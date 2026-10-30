"""Paper account (owner request 21 Oct 13:51): ₹2,00,000, risk-sized option trades, cash, limits, exact ledger."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bridge.account import Account
from bridge.costs import option_fees
from bridge.options import OptionLeg
from bridge.providers import IST, Quote


class Prov:
    def __init__(self):
        self.q = {}

    def quotes(self, keys):
        now = datetime.now(IST)
        return {k: Quote(k, v[0], now, now, bid=v[1], ask=v[2]) for k, v in self.q.items() if k in keys}


@pytest.fixture
def acct(settings):
    from bridge.store import Store
    from conftest import FakeTelegram
    prov = Prov()
    b = SimpleNamespace(store=Store(settings.db_path), provider=prov, tg=FakeTelegram(),
                        _fresh=lambda q, now, exchange_time=True: True)
    return Account(b, 200_000, risk_pct=1.0, daily_loss_pct=3.0, max_open=4), prov


T = datetime(2026, 10, 22, 10, 0, tzinfo=IST)


def leg(ask=60.0, sl=45.0, units=65, note="", und="NIFTY", key="OPT"):
    return OptionLeg(und, key, 23050, "CE", "2026-10-27", ask - 1, ask, 0.5, units, sl, ask + 15, ask + 30, ask + 45, note)


def test_sizing_risks_at_most_one_percent_and_pays_from_cash(acct):
    a, _ = acct
    note = a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "test")
    # budget 2,000; one lot risks (60-45) x 65 = 975 -> 2 lots
    assert "bought 2 lots" in note and a.cash == pytest.approx(200_000 - 2 * 65 * 60)
    assert a.equity() == pytest.approx(200_000)


def test_signal_skipped_when_one_lot_is_too_risky_or_cash_is_short(acct):
    a, _ = acct
    assert "above the ₹2,000 budget" in a.consider(T, "s1", leg(ask=200, sl=150, units=65), "SPOT", 1, [1, 2, 3, 4], 0, "x")
    assert a.cash == 200_000 and not a.positions
    assert "no tradeable option" in a.consider(T, "s2", leg(note="spread too wide"), "SPOT", 1, [1, 2, 3, 4], 0, "x")


def test_ladder_exits_breakeven_and_exact_ledger(acct):
    a, prov = acct
    a.risk_pct = 3.0                                    # budget 6,000 -> 6 lots of 975 risk
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "test")
    p = a.positions["s1"]
    assert p.lots == 6
    prov.q = {"OPT": (75, 74.0, 75.0), "SPOT": (23131, None, None)}         # T1: 2 of 6 lots out, stop -> 23100
    a.on_tick(T + timedelta(minutes=5))
    assert p.rem_lots == 4 and p.stop == pytest.approx(23100)
    prov.q = {"OPT": (62, 61.0, 62.0), "SPOT": (23099, None, None)}         # back below breakeven: rest out
    a.on_tick(T + timedelta(minutes=9))
    assert "s1" not in a.positions
    fills = a.store.db.execute("SELECT action, lots, price, cash_flow, fees, realized FROM account_fills ORDER BY id").fetchall()
    assert [f[0] for f in fills] == ["BUY", "SELL", "SELL"]
    want = (74 - 60) * 2 * 65 - option_fees(60, 74, 130, T.date()).total + (61 - 60) * 4 * 65 - option_fees(60, 61, 260, T.date()).total
    assert sum(f[5] for f in fills) == pytest.approx(want)
    assert a.cash == pytest.approx(200_000 + want)                           # the ledger reconciles to the cash


def test_square_off_at_1515_and_daily_loss_limit(acct):
    a, prov = acct
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "test")
    prov.q = {"OPT": (20, 20.0, 21.0), "SPOT": (23080, None, None)}
    a.on_tick(T.replace(hour=15, minute=15))
    assert not a.positions
    a2 = a
    a2.store.kv_set(a2.k("cash"), 190_000.0)                                # -5% on the day
    a2._last_mark = None
    a2.mark(T.replace(hour=15, minute=20))
    assert a2.store.kv_get(a2.k(f"halt_{T.date().isoformat()}"))
    assert "daily loss limit reached" in a2.consider(T.replace(hour=11), "s9", leg(), "SPOT", 1, [1, 2, 3, 4], 0, "x")


def test_no_new_entries_after_1445_or_beyond_max_open(acct):
    a, _ = acct
    assert "after 14:45" in a.consider(T.replace(hour=14, minute=50), "s1", leg(), "SPOT", 1, [1, 2, 3, 4], 0, "x")
    a.max_open = 1
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0, "x")
    assert "positions already open" in a.consider(T, "s2", leg(und="SENSEX"), "SPOT", 1, [23070, 23130, 23160, 23190], 0, "x")



def test_report_uses_the_bridge_clock_and_counts_todays_exits(acct):
    a, prov = acct
    a.b.now = lambda: T.replace(hour=15, minute=20)
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "test")
    prov.q = {"OPT": (70, 69.0, 70.0), "SPOT": (23131, None, None)}
    a.on_tick(T + timedelta(minutes=5))
    rep = a.report()
    assert "Exits today: 1 (1 with profit)" in rep and "Today: <b>+₹" in rep



def test_report_marks_open_positions_at_the_live_bid_not_the_entry(acct):
    # live 22 Oct 12:37: /account showed open positions at cost (₹28,700) while the minute curve had them at ₹26,970
    a, prov = acct
    a.b.now = lambda: T.replace(hour=10, minute=10)
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "test")   # 2 lots x 65 at 60
    prov.q = {"OPT": (52, 50.0, 52.0), "SPOT": (23090, None, None)}                   # down, above the stop
    a.on_tick(T + timedelta(minutes=5))
    assert a.positions and a.equity(prov.quotes(["OPT"])) == pytest.approx(200_000 - 2 * 65 * 10)
    rep = a.report()
    assert f"in positions ₹{2 * 65 * 50:,.0f}" in rep and "Today: <b>−₹1,300</b>" in rep


def test_two_accounts_are_independent(settings):
    from bridge.store import Store
    from conftest import FakeTelegram
    prov = Prov()
    b = SimpleNamespace(store=Store(settings.db_path), provider=prov, tg=FakeTelegram(),
                        _fresh=lambda q, now, exchange_time=True: True)
    a2, a5 = Account(b, 200_000, name="2L"), Account(b, 500_000, name="5L")
    n2 = a2.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    n5 = a5.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    assert "Account 2L: bought 2 lots" in n2 and "Account 5L: bought 5 lots" in n5      # 1% = 2,000 vs 5,000
    assert a2.cash == pytest.approx(200_000 - 2 * 65 * 60) and a5.cash == pytest.approx(500_000 - 5 * 65 * 60)
    a2b = Account(b, 200_000, name="2L")                                                 # restart: state reloads
    assert a2b.cash == a2.cash and "s1" in a2b.positions


# ---------------- loss-avoidance rules and admin controls (21 Oct evening) ----------------
def test_cost_gate_skips_trades_whose_spread_and_fees_eat_the_risk(acct):
    a, _ = acct
    wide = OptionLeg("TCS", "OPT2", 3000, "CE", "2026-10-27", 18.0, 20.0, 0.5, 175, 18.5, 21.5, 23, 24.5, "")
    note = a.consider(T, "s1", wide, "SPOT", 1, [1, 2, 3, 4], 0.0, "x")         # spread 2 vs risk 1.5
    assert "spread + fees" in note and not a.positions and a.cash == 200_000


def test_one_position_per_underlying_and_premium_cap(acct):
    a, _ = acct
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    assert "one position per underlying" in a.consider(T, "s2", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0, "x")
    a.max_deploy_pct = 6.0                                                       # 12,000 cap; 7,800 used; 1 lot = 3,900
    n = a.consider(T, "s3", leg(und="SENSEX", key="OPT3"), "SPOT", 1, [23070, 23130, 23160, 23190], 0, "x")
    assert "bought 1 lot " in n                                                  # the risk budget alone allows 2
    a.max_deploy_pct = 5.0
    assert "already in premium" in a.consider(T, "s4", leg(und="BANKNIFTY", key="OPT4"), "SPOT", 1,
                                              [23070, 23130, 23160, 23190], 0, "x")


def test_premium_stop_when_the_underlying_is_stale_and_hard_stop_always(acct):
    a, prov = acct
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    a.b._fresh = lambda q, now, exchange_time=True: False                       # underlying stale (SENSEX on 21 Oct)
    prov.q = {"OPT": (44, 44.0, 45.0), "SPOT": (23100, None, None)}
    msgs = a.on_tick(T + timedelta(minutes=3))
    assert not a.positions and "premium stop (underlying quote stale)" in msgs[0]
    a.b._fresh = lambda q, now, exchange_time=True: True
    a.consider(T, "s2", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    prov.q = {"OPT": (37, 37.0, 38.0), "SPOT": (23075, None, None)}             # 60 - 1.5 x 15 = 37.5: hard stop
    assert "hard premium stop" in a.on_tick(T + timedelta(minutes=6))[0]


def test_three_losses_in_a_row_start_a_cooldown(acct):
    a, prov = acct
    for i in range(3):
        a.consider(T + timedelta(minutes=i), f"s{i}", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
        prov.q = {"OPT": (50, 50.0, 51.0), "SPOT": (23060, None, None)}
        a.on_tick(T + timedelta(minutes=i, seconds=30))
        prov.q = {}
    assert any("3 losing exits in a row" in m for m in a.b.tg.sent)
    assert "losses in a row" in a.consider(T + timedelta(minutes=10), "s9", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0, "x")
    assert "bought" in a.consider(T + timedelta(minutes=40), "s9", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0, "x")


def test_admin_settings_are_bounded_and_survive_a_restart_and_close_sells_at_the_bid(acct):
    a, prov = acct
    assert "between" in a.set_param("risk_pct", 5)
    assert a.set_param("risk_pct", 0.5).endswith("0.5") and a.risk_pct == 0.5
    a2 = Account(a.b, 200_000, name=a.name)
    assert a2.risk_pct == 0.5
    a.set_paused(True)
    assert "paused" in a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    a.set_paused(False)
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    prov.q = {"OPT": (66, 66.0, 67.0)}
    out = a.close(T + timedelta(minutes=2), "1")
    assert "closed by admin" in out[0] and not a.positions
    assert "Account 2L: reset" in a.reset(T + timedelta(minutes=3)) and a.cash == 200_000


def _trade(a, prov, sid, t, exit_bid, und="NIFTY", key="OPT"):
    a.consider(t, sid, leg(und=und, key=key), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    prov.q = {key: (exit_bid, exit_bid, exit_bid + 1)}
    a.close(t + timedelta(minutes=1), "all")
    prov.q = {}


def test_give_back_stop_blocks_new_entries_after_half_of_a_2r_peak_is_lost(acct):
    a, prov = acct                                      # 2,00,000 at 1%: r0 = 2,000; peak must reach 4,000
    _trade(a, prov, "s1", T, 95.0)                      # 2 lots x 65 x (95 - 60) = +4,550 before fees
    assert "bought" in a.consider(T + timedelta(minutes=5), "s2", leg(und="TCS", key="O2"), "SPOT", 1,
                                  [23070, 23130, 23160, 23190], 0.0, "x")
    prov.q = {"O2": (40.0, 40.0, 41.0)}
    a.close(T + timedelta(minutes=6), "all")            # -2,600: day P&L falls below half the peak
    day = T.date().isoformat()
    st = a.store.kv_get(a.k(f"dg_{day}"))
    assert st["halt"] and st["peak"] >= 4_000 and st["pnl"] <= 0.5 * st["peak"]
    assert any("give-back stop" in m for m in a.b.tg.sent)
    note = a.consider(T + timedelta(minutes=10), "s3", leg(und="INFY", key="O3"), "SPOT", 1, [1, 2, 3, 4], 0, "x")
    assert "give-back stop" in note and "s3" not in a.positions
    a2 = Account(a.b, 200_000, name=a.name)             # the latch survives a restart
    assert "give-back stop" in a2.consider(T + timedelta(minutes=11), "s4", leg(und="SBIN", key="O4"), "SPOT", 1,
                                           [1, 2, 3, 4], 0, "x")
    assert "bought" in a2.consider(T + timedelta(days=1), "s5", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0, "x")


def test_give_back_stop_needs_a_2r_peak_first_and_leaves_open_positions_alone(acct):
    a, prov = acct
    _trade(a, prov, "s1", T, 70.0)                      # +1,300: peak below 2 x 2,000
    _trade(a, prov, "s2", T + timedelta(minutes=5), 59.0, und="TCS", key="O2")
    assert not (a.store.kv_get(a.k(f"dg_{T.date().isoformat()}")) or {}).get("halt")
    assert "bought" in a.consider(T + timedelta(minutes=10), "s3", leg(und="INFY", key="O3"), "SPOT", 1,
                                  [23070, 23130, 23160, 23190], 0.0, "x")
    b, prov2 = acct
    day = T.date().isoformat()
    b.store.kv_set(b.k(f"dg_{day}"), {"pnl": 1000.0, "peak": 5000.0, "halt": "10:20"})
    prov2.q = {"O3": (75, 74.0, 75.0), "SPOT": (23131, None, None)}         # the open position still takes T1
    assert any("T1" in m for m in b.on_tick(T + timedelta(minutes=12)))


# ---------------- five strategy accounts (evidence/strategy_accounts_protocol.md, 22 Oct evening) ----------------
def mk(acct, strategy, name, **kw):
    a, prov = acct
    return Account(a.b, 500_000, name=name, strategy=strategy, **kw), prov


LV = [23070, 23130, 23160, 23190]               # SL / T1 / T2 / T3 around an entry of 23,100 (R = 30)


def test_concentrated_risks_five_percent_full_size_and_at_most_three_a_day(acct):
    c, prov = mk(acct, "concentrated", "CONC")
    assert c.risk_pct == 5.0 and c.max_open == 3 and c.daily_loss_pct == 10.0 and c.max_deploy_pct == 90.0
    assert "bought 25 lots" in c.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x")            # 25,000 / 975
    n = c.consider(T, "s2", leg(und="TCS", key="O2"), "SPOT", 1, LV, 0.0, "x", risk_scale=0.25)
    assert "bought 25 lots" in n                                                                # stock: no 0.25x here
    c.consider(T, "s3", leg(und="SENSEX", key="O3"), "SPOT", 1, LV, 0.0, "x")
    prov.q = {"OPT": (61, 60.0, 61.0)}
    c.close(T + timedelta(minutes=1), "s1")                                    # room again, but the day's 3 are used
    assert "3 entries already today" in c.consider(T, "s4", leg(und="INFY", key="O4"), "SPOT", 1, LV, 0.0, "x")


def test_wide_doubles_the_stop_and_targets_and_halves_the_lots(acct):
    w, _ = mk(acct, "wide", "WIDE")
    assert "bought 2 lots" in w.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x")         # 5,000 / (2 x 15 x 65)
    p = w.positions["s1"]
    assert p.levels == pytest.approx([23040, 23160, 23220, 23280]) and p.opt_sl == pytest.approx(30.0)
    s = w.consider(T, "s2", leg(und="TCS", key="O2"), "SPOT", -1, [23130, 23070, 23040, 23010], 0.0, "x")
    assert w.positions["s2"].levels == pytest.approx([23160, 23040, 22980, 22920]) and "bought" in s


def test_confirm_waits_for_half_r_then_buys_at_the_live_ask_or_lets_it_lapse(acct):
    f, prov = mk(acct, "confirm", "CONF")
    note = f.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x")
    assert "waiting" in note and "23,115" in note and not f.positions and f.cash == 500_000
    prov.q = {"OPT": (64, 63.0, 64.0), "SPOT": (23110, None, None)}
    f.on_tick(T + timedelta(minutes=2))
    assert not f.positions
    f2 = Account(f.b, 500_000, name="CONF", strategy="confirm")                         # a restart keeps the wait
    prov.q = {"OPT": (66, 65.0, 66.0), "SPOT": (23116, None, None)}
    f2.on_tick(T + timedelta(minutes=4))
    p = f2.positions["s1"]
    assert p.entry == 66.0 and p.opt_sl == pytest.approx(66 - 22.5) and p.levels == LV
    assert p.lots == 3                                                                # 5,000 // (22.5 x 65)
    f2.consider(T + timedelta(minutes=5), "s2", leg(und="TCS", key="O2"), "SPOT2", 1, LV, 0.0, "x")
    prov.q = {"O2": (60, 59.0, 60.0), "SPOT2": (23110, None, None), "OPT": (66, 65.0, 66.0), "SPOT": (23116, None, None)}
    f2.on_tick(T + timedelta(minutes=21))                                             # 16 minutes: lapsed
    prov.q["SPOT2"] = (23120, None, None)
    f2.on_tick(T + timedelta(minutes=22))
    assert "s2" not in f2.positions and not f2.pending


def test_cluster_allows_two_same_direction_entries_per_30_minutes_and_has_a_time_stop(acct):
    c, prov = mk(acct, "cluster", "CLUS")
    c.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x")
    c.consider(T + timedelta(minutes=5), "s2", leg(und="TCS", key="O2"), "SPOT", 1, LV, 0.0, "x")
    assert "2 BUY entries in the last 30 minutes" in c.consider(T + timedelta(minutes=10), "s3",
                                                                 leg(und="INFY", key="O3"), "SPOT", 1, LV, 0.0, "x")
    assert "bought" in c.consider(T + timedelta(minutes=10), "s4", leg(und="SBIN", key="O4"), "SPOT", -1,
                                  [23130, 23070, 23040, 23010], 0.0, "x")
    assert "bought" in c.consider(T + timedelta(minutes=31), "s5", leg(und="ITC", key="O5"), "SPOT", 1, LV, 0.0, "x")
    prov.q = {"OPT": (58, 57.0, 58.0), "O2": (61, 60.0, 61.0), "O4": (60, 59.0, 60.0), "O5": (60, 59.0, 60.0),
              "SPOT": (23100, None, None)}
    c.on_tick(T + timedelta(minutes=30))                                       # s1 is 30 minutes old, below T1
    assert "s1" not in c.positions and "s2" in c.positions
    last = c.store.db.execute("SELECT reason FROM account_fills WHERE acct='CLUS' ORDER BY id DESC LIMIT 1").fetchone()
    assert last[0] == "30-minute time stop"


def test_quiet_accounts_trade_without_sending_messages(acct):
    q, prov = mk(acct, "base", "Q", quiet=True)
    assert q.consider(T, "s0", leg(note="spread too wide"), "SPOT", 1, LV, 0.0, "x") == ""
    assert "bought" in q.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x")            # a buy is still noted
    prov.q = {"OPT": (50, 50.0, 51.0), "SPOT": (23060, None, None)}
    assert q.on_tick(T + timedelta(minutes=3)) == [] and "s1" not in q.positions


def test_accounts_setting_takes_an_optional_strategy(tmp_path, monkeypatch):
    from bridge.config import Settings
    env = tmp_path / ".env"
    env.write_text("ACCOUNTS=5L:500000,CONC:500000:concentrated,WIDE:500000:wide\n")
    monkeypatch.delenv("ACCOUNTS", raising=False)
    s = Settings.from_env(env)
    monkeypatch.delenv("ACCOUNTS", raising=False)
    assert s.accounts == {"5L": 500_000, "CONC": 500_000, "WIDE": 500_000}
    assert s.account_strategies == {"5L": "base", "CONC": "concentrated", "WIDE": "wide"}


def test_risk_view_shows_direction_and_the_loss_if_every_stop_is_hit(acct):
    # 22 Oct 12:12: four SELL positions were one market bet, and nothing said so
    a, prov = acct
    a.consider(T, "s1", leg(), "SPOT", -1, [23130, 23070, 23040, 23010], 0.0, "x")          # 2 lots, risk 15 x 130
    a.consider(T, "s2", leg(und="TCS", key="O2"), "SPOT", -1, [23130, 23070, 23040, 23010], 0.0, "x")
    n3 = a.consider(T, "s3", leg(und="INFY", key="O3"), "SPOT", -1, [23130, 23070, 23040, 23010], 0.0, "x")
    assert "3 SELL positions open" in n3 and "one market move" in n3
    x = a.exposure()
    assert x["sell"] == 3 and x["buy"] == 0 and x["at_risk"] == pytest.approx(3 * 2 * 65 * 15)
    rep = a.report()
    assert "Risk now: 3 SELL / 0 BUY" in rep and f"₹{3 * 2 * 65 * 15:,.0f}" in rep
    b = a.consider(T, "s4", leg(und="SBIN", key="O4"), "SPOT", 1, LV, 0.0, "x")
    assert "one market move" not in b                                               # mixed directions: no warning


def test_wide4_uses_four_times_the_stop_and_targets_and_risks_at_most_the_premium(acct):
    # evidence/wide_stop_result.md: K4 lost least on 2022-24 (-0.034R); WID4 measures it live through options
    w, _ = mk(acct, "wide4", "WID4")
    note = w.consider(T, "s1", leg(), "SPOT", 1, LV, 0.0, "x")       # premium stop 60 - 4 x 15 = 0 -> floored at 0.05
    p = w.positions["s1"]
    assert p.levels == pytest.approx([22980, 23220, 23340, 23460]) and p.opt_sl == pytest.approx(0.05)
    assert "bought 1 lot " in note                                   # 5,000 // (59.95 x 65 = 3,897) = 1 lot


def test_after_t1_a_runner_never_turns_into_a_loss_on_the_option(acct):
    # live 23 Oct: HINDZINC/PFC/SENSEX runners hit T1, then rode back to the UNDERLYING's breakeven over hours and
    # exited below the premium paid (-4,148, -3,430, -907). Breakeven must hold on the option itself.
    a, prov = acct
    a.risk_pct = 3.0                                                       # 6 lots, so a runner remains after T1
    a.consider(T, "s1", leg(), "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    prov.q = {"OPT": (75, 74.0, 75.0), "SPOT": (23131, None, None)}        # T1: 2 of 6 lots out
    a.on_tick(T + timedelta(minutes=5))
    p = a.positions["s1"]
    assert p.hits == 1 and p.rem_lots == 4
    prov.q = {"OPT": (60.4, 60.2, 60.6), "SPOT": (23112, None, None)}      # stock still above 23,100; option at cost
    a.on_tick(T + timedelta(minutes=90))
    assert "s1" not in a.positions
    last = a.store.db.execute("SELECT price, realized, reason FROM account_fills ORDER BY id DESC LIMIT 1").fetchone()
    assert last[2] == "breakeven (option at cost)" and last[1] > -150      # fees only, not a real loss
    first = a.store.db.execute("SELECT realized FROM account_fills WHERE action='SELL' ORDER BY id LIMIT 1").fetchone()
    assert first[0] > 0
