"""Owner requests of 20 Oct 2026: option entries with SL/targets for every signal, SENSEX, an F&O scanner (top gainers,
losers, volume surges) with levels, and paper books for all of them."""
from datetime import date, datetime, timedelta

import numpy as np
import pandas as pd
import pytest

from bridge.costs import option_fees
from bridge.options import OptionBook, eligible_expiry, pick_leg
from bridge.providers import IST, Quote, front_future
from conftest import T0, FakeTelegram, StubProvider, make_payload, sig


class OptStub(StubProvider):
    """The normal stub, plus option quotes (bid/ask set per key) for the options book."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        self.opt = {}

    def quotes(self, keys):
        out = super().quotes([k for k in keys if k not in self.opt])
        now = self.clock()
        for k in keys:
            if k in self.opt:
                b, a = self.opt[k]
                out[k] = Quote(k, (b + a) / 2 if b else 0.0, now, now, bid=b, ask=a)
        return out


def test_eligible_expiry_skips_today():
    assert eligible_expiry(["2026-10-21", "2026-10-28"], date(2026, 10, 21)) == "2026-10-28"
    assert eligible_expiry(["2026-10-21"], date(2026, 10, 21)) is None


def test_option_leg_buy_signal_is_the_1itm_call_with_delta_mapped_levels():
    prov = StubProvider(make_payload(spot=25012.0))
    leg = pick_leg(prov, "NSE_INDEX|Nifty 50", "NIFTY", 25012.0, +1, 25000.0, 24960.0, (25040.0, 25080.0, 25120.0), 65,
                   T0.date())
    assert (leg.strike, leg.typ) == (25000.0, "CE") and not leg.note        # highest strike below spot
    assert leg.sl == pytest.approx(leg.ask - 0.5 * 40, abs=0.05)             # delta 0.5 x 40 points of risk
    assert leg.t1 == pytest.approx(leg.ask + 0.5 * 40, abs=0.05) and leg.t3 == pytest.approx(leg.ask + 0.5 * 120, abs=0.05)
    put = pick_leg(prov, "NSE_INDEX|Nifty 50", "NIFTY", 25012.0, -1, 25000.0, 25040.0, (24960.0, 24920.0, 24880.0), 65,
                   T0.date())
    assert (put.strike, put.typ) == (25050.0, "PE") and put.sl < put.ask < put.t1   # SELL -> buy the put; premium SL below


def test_option_leg_with_a_wide_spread_is_shown_but_not_traded():
    p = make_payload(spot=25012.0)
    for row in p["data"]:
        row["call_options"]["market_data"].update(bid_price=10.0, ask_price=14.0)
    leg = pick_leg(StubProvider(p), "NSE_INDEX|Nifty 50", "NIFTY", 25012.0, +1, 25000.0, 24960.0,
                   (25040.0, 25080.0, 25120.0), 65, T0.date())
    assert "spread" in leg.note and "not traded" in leg.line()


def test_option_book_exits_at_the_live_bid_with_fees_and_never_invents_a_fill(settings, clock):
    from bridge.store import Store
    prov = OptStub(make_payload(), clock=clock)
    book = OptionBook(Store(settings.db_path), prov)
    leg = pick_leg(prov, "NSE_INDEX|Nifty 50", "NIFTY", 25012.0, +1, 25000.0, 24960.0, (25040.0, 25080.0, 25120.0),
                   65, clock().date())
    assert book.open("s1", "executable", leg, 40.0, clock())
    assert not book.open("s1", "executable", leg, 40.0, clock())            # one leg per signal
    book.request_close("s1", "executable", "T3")
    prov.opt[leg.key] = (None, None)                                         # no bid yet: retried, not invented
    assert book.settle(clock()) == []
    prov.opt[leg.key] = (leg.ask + 15.0, leg.ask + 15.5)
    ((bk, msg),) = book.settle(clock.advance(seconds=30))
    net = book.store.db.execute("SELECT net_inr FROM option_trades WHERE sid='s1'").fetchone()[0]
    assert net == pytest.approx(15.0 * 65 - option_fees(leg.ask, leg.ask + 15.0, 65, clock().date()).total)
    assert "sold at" in msg and "after costs" in msg and "closed 1" in book.report()


def test_engine_signal_opens_futures_and_option_leg_and_the_leg_follows_the_futures_exit(settings, clock):
    from bridge.service import Bridge
    from bridge.store import Store
    prov = OptStub(make_payload(), clock=clock)
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    text = b.handle_payload(sig(clock=clock, sid="ENG-1"), "engine")
    assert "Source: NFCE engine" in text and "executable book: entered" in text
    assert "Option leg (buy): NIFTY 24950 CE" in text and "paper: bought at the ask" in text   # spot 25,000
    key = b.store.db.execute("SELECT key FROM option_trades WHERE sid='ENG-1'").fetchone()[0]
    prov.opt[key] = (30.0, 30.5)
    prov.fut_price = 24950.0                                                 # futures through the stop
    clock.advance(seconds=20)
    b.tick()
    st = b.store.db.execute("SELECT status, exit FROM option_trades WHERE sid='ENG-1'").fetchone()
    assert st == ("CLOSED", 30.0)


def test_manual_check_shows_the_option_leg_without_paper(make_bridge, clock):
    b, prov, tg = make_bridge()
    text = b.handle_command("/check BUY 25000 24960")
    assert "Option leg (buy)" in text and "paper: bought" not in text


def test_sensex_futures_come_from_the_bse_file():
    rows = [{"segment": "BSE_FO", "instrument_type": "FUT", "underlying_symbol": "SENSEX", "instrument_key": "BSE_FO|864571",
             "expiry": int(datetime(2026, 10, 29, 15, 30, tzinfo=IST).timestamp() * 1000), "lot_size": 20, "tick_size": 5.0,
             "trading_symbol": "SENSEX FUT 29 OCT 26"}]
    f = front_future(rows, "SENSEX", date(2026, 10, 21))
    assert f.instrument_key == "BSE_FO|864571" and f.lot_size == 20


def test_free_text_is_saved_as_a_note_not_answered_as_a_command(make_bridge):
    b, prov, tg = make_bridge()
    reply = b.handle_command("Focus on Nifty 50 calls/ puts")
    assert reply.startswith("📝 Noted") and b.store.count("events") == 1


# ---------------- F&O scanner ----------------
def stock_rows(px, days=25, vol=1000.0, seed=0):
    rng = np.random.default_rng(seed)
    out = []
    for d in pd.bdate_range("2026-09-14", periods=days):
        for t in pd.date_range(pd.Timestamp(d).tz_localize("Asia/Kolkata") + pd.Timedelta(hours=9, minutes=15),
                               periods=75, freq="5min"):
            c = px * (1 + rng.normal(0, 0.002))
            out.append([t.isoformat(), px, max(px, c) * 1.001, min(px, c) * 0.999, c, vol, 0])
            px = c
    return out


class ScanStub(OptStub):
    """Six F&O stocks with history, live quotes (prev close, volume, open) and futures quotes."""
    LIVE = {"AAA": (1.05, 3000), "BBB": (1.03, 1100), "CCC": (1.01, 900), "DDD": (0.96, 1000), "EEE": (0.99, 6000),
            "FFF": (1.002, 1000)}

    def fno_stocks(self, today):
        return [{"symbol": s, "equity_key": f"NSE_EQ|{s}", "fut_key": f"NSE_FO|F{s}", "lot": 500, "tick": 0.05,
                 "expiry": date(2026, 10, 27)} for s in self.LIVE]

    def candles_5m(self, key, start, end, intraday=False, minutes=5):
        return stock_rows(1000.0, seed=hash(key) % 100)

    def quotes(self, keys):
        now = self.clock()
        out = {}
        rest = []
        for k in keys:
            sym = k.split("|")[-1][1:] if k.startswith("NSE_FO|F") else k.split("|")[-1]
            if k.startswith("NSE_EQ|") and sym in self.LIVE:
                m, v = self.LIVE[sym]
                pc = 1000.0
                out[k] = Quote(k, pc * m, now - timedelta(seconds=1), now, prev_close=pc, volume=v * 12,
                               day_open=pc * (1 + (m - 1) / 2))
            elif k.startswith("NSE_FO|F") and sym in self.LIVE:
                px = 1000.0 * self.LIVE[sym][0] + 2.0
                out[k] = Quote(k, px, now - timedelta(seconds=1), now, bid=px - 0.05, ask=px + 0.05)
            else:
                rest.append(k)
        out.update(super().quotes(rest))
        return out


def test_scanner_ranks_gainers_losers_and_volume_surges_and_paper_trades_them(settings, clock):
    from bridge.scanner import Scanner
    from bridge.service import Bridge
    from bridge.store import Store
    settings.option_legs = False
    settings.scanner_mode = "trade"                       # the old paper-trading scanner is still available
    clock.set(datetime(2026, 10, 21, 10, 16, tzinfo=IST))
    prov = ScanStub(make_payload(), clock=clock)
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    sc = Scanner(b)
    assert sc.ensure_loaded(clock().date(), background=False)
    lists = sc.rank(clock(), "10:15")
    assert list(lists["gainers"].symbol) == ["AAA", "BBB", "CCC", "FFF"] and list(lists["losers"].symbol) == ["DDD", "EEE"]
    assert set(lists["surges"].symbol) == set()                    # AAA/EEE are already gainer/loser: no duplicates
    text = sc.scan(clock(), "10:15")
    assert "Top 5 gainers" in text and "NO EDGE" in text and "AAA +5.0%" in text and "SL" in text
    rows = b.store.db.execute("SELECT underlying, side, entry, sl FROM paper_trades WHERE book='scanner'").fetchall()
    aaa = [r for r in rows if r[0] == "AAA"]
    assert aaa and aaa[0][1] == 1 and aaa[0][3] < aaa[0][2]                        # futures entry, stop below
    prov.LIVE = {**prov.LIVE, "AAA": (0.90, 3000)}                                # AAA future collapses
    clock.advance(seconds=30)
    b.refresh_stock_futures(clock())
    st = b.store.db.execute("SELECT status FROM paper_trades WHERE book='scanner' AND underlying='AAA'").fetchall()
    assert ("CLOSED",) in st
    assert "Scanner paper book: closed" in b.scanner_report()


def test_long_messages_are_split_on_line_breaks_not_truncated():
    from bridge.telegram import split_message
    text = "\n".join(f"line {i} " + "x" * 200 for i in range(60))
    parts = split_message(text)
    assert len(parts) > 1 and all(len(p) <= 3900 for p in parts) and "\n".join(parts) == text



# ---------------- first-minutes timing (pre-flight audit, 21 Oct 00:50) ----------------
def test_range_forecast_outside_its_hours_downloads_nothing():
    from bridge.range_model import RangeError, RangeForecaster

    class Counting:
        calls = 0

        def candles_5m(self, *a, **k):
            Counting.calls += 1
            return []
    rf = RangeForecaster(Counting())
    with pytest.raises(RangeError, match="hours"):
        rf.forecast("NIFTY", datetime(2026, 10, 21, 9, 21, tzinfo=IST), False)
    assert Counting.calls == 0


def test_engine_waits_when_upstox_history_lags_a_day():
    from types import SimpleNamespace
    from bridge.live_engine import LiveEngine
    idx = pd.date_range("2026-10-16 09:15", periods=3, freq="5min", tz="Asia/Kolkata")
    bars = pd.DataFrame({"close": [25000.0, 25010.0, 25020.0]}, index=idx)
    now = datetime(2026, 10, 21, 9, 25, tzinfo=IST)
    prov = SimpleNamespace(quotes=lambda keys: {"F": Quote("F", 25300, now, now, prev_close=25250.0)})
    eng = LiveEngine(SimpleNamespace(s=SimpleNamespace(underlyings={"NIFTY": "x"}), provider=prov,
                                     keys=lambda r: ("F", "x")), ["NIFTY"])
    assert "lagging" in eng.history_lag("NIFTY", bars, now.date())
    prov.quotes = lambda keys: {"F": Quote("F", 25300, now, now, prev_close=25030.0)}     # settlement within 0.5%
    assert eng.history_lag("NIFTY", bars, now.date()) is None


def test_premarket_warm_up_runs_once_per_day(make_bridge, clock):
    b, prov, tg = make_bridge()
    warmed = []
    b.ranger.warm = lambda now: warmed.append(now)
    clock.set(datetime(2026, 10, 21, 8, 50, tzinfo=IST))
    b.tick()
    b.tick()
    assert len(warmed) == 1 and any(m.startswith("Pre-market") for m in tg.sent)



def test_admin_messages_are_flagged_for_the_assistant_and_sent_messages_are_logged(make_bridge):
    b, prov, tg = make_bridge()
    b.s.assistant_relay = True
    reply = b.handle_command("@admin: tomorrow add a 5L account and keep the books running")
    assert reply.startswith("📨 Saved and passed to your assistant")
    rows = b.store.db.execute("SELECT source, raw FROM events ORDER BY id").fetchall()
    assert rows[0][0] == "telegram-admin" and "5L account" in rows[0][1]
    sent = b.store.db.execute("SELECT text FROM sent_messages").fetchall()
    assert any("passed to your assistant" in t for (t,) in sent)



# ---------------- 3-minute NFCE for every F&O stock (owner request 21 Oct 09:46) ----------------
def test_stock_3m_bars_come_from_complete_1m_triples_only():
    from types import SimpleNamespace
    from bridge.stock_engine import StockEngine
    eng = StockEngine(SimpleNamespace(provider=None, s=None))
    eng.hist = {"AAA": pd.DataFrame(columns=["open", "high", "low", "close", "volume", "oi"])}
    t0 = int(pd.Timestamp("2026-10-21 09:30", tz="Asia/Kolkata").timestamp() * 1000)
    m = 60000
    eng.minutes["AAA"] = {t0: [10, 11, 9, 10.5, 100], t0 + m: [10.5, 12, 10, 11, 50], t0 + 2 * m: [11, 11.5, 10.8, 11.2, 25],
                          t0 + 3 * m: [11.2, 11.3, 11, 11.1, 10]}            # the 09:33 bar is missing two minutes
    b = eng.bars("AAA", datetime(2026, 10, 21, 9, 40, tzinfo=IST))
    assert list(b.index.strftime("%H:%M")) == ["09:30"]
    r = b.iloc[0]
    assert (r.open, r.high, r.low, r.close, r.volume) == (10, 12, 9, 11.2, 175)


def test_stock_3m_signals_of_one_bar_go_out_in_one_message(settings, clock):
    from bridge.service import Bridge
    from bridge.stock_engine import StockEngine
    from bridge.store import Store
    settings.option_legs = False
    prov = ScanStub(make_payload(), clock=clock)
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    eng = StockEngine(b)
    u = {"symbol": "AAA", "equity_key": "NSE_EQ|AAA", "fut_key": "NSE_FO|FAAA", "lot": 500, "tick": 0.05}
    eng.run_slot = lambda slot, now: [(u, 1, 1050.0, 10.0, 72.0), (dict(u, symbol="DDD", fut_key="NSE_FO|FDDD"), -1, 960.0, 8.0, 70.0)]
    eng._work(clock(), clock())
    (msg,) = [m for m in b.tg.sent if m.startswith("🧾 <b>Stock signals")]
    assert "🟩 BUY <b>AAA</b>" in msg and "Entry <b>1,050.00</b> · SL <b>1,040.00</b> · T <b>1,060.00</b>" in msg
    assert "🟥 SELL <b>DDD</b>" in msg and "no proven edge" in msg
    rows = b.store.db.execute("SELECT underlying, side FROM paper_trades WHERE book='stock3m'").fetchall()
    assert sorted(rows) == [("AAA", 1), ("DDD", -1)]



def test_early_mode_runs_the_first_15_minutes_with_the_opening_skip_off(monkeypatch):
    import nfce
    from types import SimpleNamespace
    from bridge.stock_engine import StockEngine
    seen = []
    monkeypatch.setattr(nfce, "prepare", lambda b, tf, p, **k: seen.append(p.skip_open))
    monkeypatch.setattr(nfce, "run", lambda *a, **k: [])
    eng = StockEngine(SimpleNamespace(provider=None, s=None))
    idx = pd.date_range("2026-09-01 09:15", periods=400, freq="3min", tz="Asia/Kolkata")
    eng.universe = [{"symbol": "AAA"}]
    for slot_hm, want in (("09:21", 0), ("09:36", 15)):          # EARLY still computed (information), never traded
        slot = pd.Timestamp(f"2026-10-21 {slot_hm}", tz="Asia/Kolkata")
        bars = pd.DataFrame({"open": 1.0, "high": 1.0, "low": 1.0, "close": 1.0, "volume": 1.0, "oi": 0.0},
                            index=idx.append(pd.DatetimeIndex([slot - pd.Timedelta(minutes=3)])))
        eng.bars = lambda sym, now, b=bars: b if sym == "AAA" else pd.DataFrame(columns=["open", "close"])
        eng.hist = {"AAA": bars}
        eng.run_slot(slot.to_pydatetime(), slot.to_pydatetime())
        assert seen[-1] == want



def test_stock_with_no_history_does_not_break_the_bar_builder():
    from types import SimpleNamespace
    from bridge.live_engine import frame
    from bridge.stock_engine import StockEngine
    eng = StockEngine(SimpleNamespace(provider=None, s=None))
    eng.hist = {"AAA": frame([], 3)}
    t0 = int(pd.Timestamp("2026-10-21 09:30", tz="Asia/Kolkata").timestamp() * 1000)
    eng.minutes["AAA"] = {t0 + k * 60000: [10, 11, 9, 10.5, 100] for k in range(3)}
    assert len(eng.bars("AAA", datetime(2026, 10, 21, 9, 40, tzinfo=IST))) == 1
    assert eng.bars("BBB", datetime(2026, 10, 21, 9, 40, tzinfo=IST)).empty



def test_watchlist_mode_shows_movers_without_trades_and_tags_signals(settings, clock):
    from bridge.scanner import Scanner
    from bridge.service import Bridge
    from bridge.store import Store
    clock.set(datetime(2026, 10, 21, 10, 16, tzinfo=IST))
    prov = ScanStub(make_payload(), clock=clock)
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    sc = Scanner(b)
    b.scanner = sc
    sc.ensure_loaded(clock().date(), background=False)
    text = sc.step(clock())
    assert text.startswith("👀 <b>F&amp;O Watchlist") and "<b>AAA</b>  +5.0%" in text and "BUY" not in text
    assert b.store.db.execute("SELECT COUNT(*) FROM paper_trades WHERE book='scanner'").fetchone()[0] == 0
    assert sc.watch["AAA"].startswith("top gainer")


def test_one_engine_signal_reaches_all_five_strategy_accounts_and_only_5L_talks(settings, clock):
    # dress rehearsal for 23 Oct (evidence/strategy_accounts_protocol.md): the real Bridge, one NIFTY engine signal
    from bridge.service import Bridge
    from bridge.store import Store
    settings.accounts = {n: 500_000 for n in ("5L", "CONC", "WIDE", "CONF", "CLUS")}
    settings.account_strategies = {"5L": "base", "CONC": "concentrated", "WIDE": "wide", "CONF": "confirm",
                                   "CLUS": "cluster"}
    prov = OptStub(make_payload(), clock=clock)
    tg = FakeTelegram()
    b = Bridge(settings, prov, Store(settings.db_path), tg, clock=clock)
    text = b.handle_payload(sig(clock=clock, sid="ENG-1"), "engine")
    a = {x.name: x for x in b.accounts}
    assert "Account 5L: bought" in text and "Account CONC: bought" in text and "Account WIDE: bought" in text
    assert "Account CLUS: bought" in text and "CONF" not in text            # quiet: its wait is not shown
    assert "ENG-1" in a["CONF"].pending and not a["CONF"].positions
    assert a["CONC"].positions["ENG-1"].lots > a["5L"].positions["ENG-1"].lots > a["WIDE"].positions["ENG-1"].lots
    key = a["5L"].positions["ENG-1"].key
    prov.opt[key] = (30.0, 30.5)
    prov.fut_price = 24900.0                                                 # everything through the stop
    for row in prov.payload["data"]:
        row["underlying_spot_price"] = 24900.0
    n_before = len(tg.sent)
    clock.advance(seconds=20)
    b.tick()
    for name in ("5L", "CONC", "WIDE", "CLUS"):
        assert "ENG-1" not in a[name].positions, name
    sold = [m for m in tg.sent[n_before:] if "sold" in m and "Account" in m]
    assert sold and all("Account 5L" in m for m in sold)                     # only 5L's exit is sent
    assert "Strategy accounts" in b.accounts_text() and "<b>CONF</b> (confirm)" in b.accounts_text()



def test_sell_only_scanner_trades_the_losers_and_only_watches_the_gainers(settings, clock):
    # 23 Oct: buying the top gainers lost on all 3 live days (-71,410 on 23 Oct) and in every 2022-24 row
    # (evidence/leads_2day_result.md); SCANNER_MODE=sell keeps the SELL picks and turns the BUY side into a watchlist
    from bridge.scanner import Scanner
    from bridge.service import Bridge
    from bridge.store import Store
    settings.option_legs = False
    settings.scanner_mode = "sell"
    clock.set(datetime(2026, 10, 21, 10, 16, tzinfo=IST))
    prov = ScanStub(make_payload(), clock=clock)
    b = Bridge(settings, prov, Store(settings.db_path), FakeTelegram(), clock=clock)
    sc = Scanner(b)
    assert sc.ensure_loaded(clock().date(), background=False)
    text = sc.scan(clock(), "10:15")
    sides = {r[0]: r[1] for r in b.store.db.execute("SELECT underlying, side FROM paper_trades WHERE book='scanner'")}
    assert sides and all(v == -1 for v in sides.values())                 # only SELL picks are paper-traded
    assert "DDD" in sides and "AAA" not in sides
    assert "watch only" in sc.human_text and "AAA" in sc.human_text       # gainers still shown, as a watchlist
    assert "BUY" not in sc.human_text.split("watch only")[1].split("Top losers")[0]


def test_scanner_mode_setting_accepts_sell(tmp_path, monkeypatch):
    from bridge.config import Settings
    env = tmp_path / ".env"
    env.write_text("SCANNER_MODE=sell\n")
    monkeypatch.delenv("SCANNER_MODE", raising=False)
    s = Settings.from_env(env)
    monkeypatch.delenv("SCANNER_MODE", raising=False)
    assert s.scanner_mode == "sell"


def test_volume_surge_picks_say_the_move_since_the_open_not_only_the_day_change():
    # 26 Oct: DRREDDY showed "SELL +1.3%": the rule trades the move since the open (it gapped up, then fell below the
    # open), but the alert only showed the change vs yesterday's close, so it read as a contradiction
    from bridge.scanner import since_open_line
    line = since_open_line("G2", 1245.3, 1260.0, 0.013)
    assert "-1.2% since the open" in line and "+1.3% vs yesterday" in line
    assert since_open_line("G1", 1245.3, 1260.0, 0.013) == "" and since_open_line("G2", 100.0, None, 0.0) == ""
