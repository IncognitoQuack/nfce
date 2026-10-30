"""gs/types.py and gs/store.py: immutable records, deterministic IDs, append-only WAL store, restart idempotence."""
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from gs import store as st  # noqa: E402
from gs.types import Event, ExecutionEvent, FeatureSnapshot, Intent, Leg, StopRule, Verdict, make_id  # noqa: E402

IST = ZoneInfo("Asia/Kolkata")
T0 = datetime(2026, 10, 27, 9, 30, tzinfo=IST)


def intent(t=T0, alpha="GS-SIP-1"):
    return Intent(make_id("in", alpha, t, "RELIANCE"), alpha, t, (Leg("NSE_EQ|RELIANCE", 1, 70, 1400.0),),
                  t + timedelta(seconds=2), t + timedelta(seconds=180), StopRule(1390.0, t.replace(hour=15, minute=15)),
                  700.0, ("ev-1",), "sha")


def test_ids_are_deterministic_and_content_addressed():
    a = Event.new("NSE_EQ|X", "quote", T0, {"bid": 1.0, "ask": 1.1})
    b = Event.new("NSE_EQ|X", "quote", T0, {"ask": 1.1, "bid": 1.0})
    c = Event.new("NSE_EQ|X", "quote", T0, {"bid": 1.0, "ask": 1.2})
    assert a.event_id == b.event_id != c.event_id
    assert intent().intent_id == intent().intent_id


def test_records_refuse_naive_times_and_time_travel():
    with pytest.raises(ValueError):
        Event.new("X", "quote", datetime(2026, 10, 27, 9, 30), {})
    with pytest.raises(ValueError):
        Event("e", "X", None, T0, T0 - timedelta(seconds=1), "quote", {})
    with pytest.raises(ValueError):
        FeatureSnapshot(T0, {"atr": 1.0}, T0 + timedelta(seconds=1))
    with pytest.raises(ValueError):
        Intent("i", "a", T0, (), T0 - timedelta(seconds=1), T0, StopRule(), 0.0, (), "")
    with pytest.raises(ValueError):
        Verdict("p", "MAYBE", {})
    with pytest.raises(ValueError):
        Leg("X", 0, 1)


def test_store_is_wal_append_only_and_idempotent(tmp_path):
    s = st.Store(tmp_path / "gs.db")
    assert s.con.execute("pragma journal_mode").fetchone()[0] == "wal"
    e = Event.new("NSE_EQ|X", "quote", T0, {"bid": 1.0})
    assert s.append_event(e) and not s.append_event(e)                    # second insert ignored
    for sql in ("update events set kind = 'x'", "delete from events"):
        with pytest.raises(sqlite3.IntegrityError):
            s.con.execute(sql)
    assert len(s.events()) == 1 and s.integrity_check()


def test_events_replay_in_availability_order_across_offsets(tmp_path):
    s = st.Store(tmp_path / "gs.db")
    late = Event.new("A", "quote", T0, {"n": 1}, available_at=T0 + timedelta(seconds=5))
    utc_early = Event.new("B", "quote", (T0 + timedelta(seconds=1)).astimezone(timezone.utc), {"n": 2})
    for e in (late, utc_early):
        s.append_event(e)
    got = s.events()
    assert [g.instrument_id for g in got] == ["B", "A"]
    assert s.events(end=T0 + timedelta(seconds=2))[0].instrument_id == "B"      # nothing later than the cut
    assert got[1].payload == {"n": 1} and got[1].available_at == late.available_at


def test_restart_replay_does_not_duplicate_intents_or_fills(tmp_path):
    p = tmp_path / "gs.db"
    s = st.Store(p)
    it = intent()
    fx = ExecutionEvent.new(it.intent_id, 0, T0 + timedelta(seconds=3), "fill", instrument_id="NSE_EQ|RELIANCE",
                            side=1, qty=70, price=1400.0, fee=20.0, scenario="strict")
    assert s.append_intent(it) and s.append_execution(fx)
    s.close()
    s2 = st.Store(p)                                                       # restart, replay the same records
    assert not s2.append_intent(intent()) and not s2.append_execution(fx)
    assert len(s2.intents()) == 1 and len(s2.executions(it.intent_id)) == 1


def test_snapshots_are_revisions_and_the_latest_wins(tmp_path):
    s = st.Store(tmp_path / "gs.db")
    s.append_snapshot("risk_state", "SIP", T0, {"dg": False})
    s.append_snapshot("risk_state", "SIP", T0 + timedelta(minutes=1), {"dg": True})
    assert s.latest_snapshot("risk_state", "SIP") == {"dg": True}
    assert s.latest_snapshot("risk_state", "OVN") is None
    with pytest.raises(ValueError):
        s.append_snapshot("events", "SIP", T0, {})


def test_one_verdict_per_protocol_and_backup(tmp_path):
    s = st.Store(tmp_path / "gs.db")
    assert s.freeze_protocol("GS-SIP-1", "abc", T0, {"n": 1000}) and not s.freeze_protocol("GS-SIP-1", "zzz", T0, {})
    assert s.protocol("GS-SIP-1")["sha256"] == "abc"
    s.record_verdict("GS-SIP-1", T0, {"verdict": "FAIL"})
    with pytest.raises(st.AppendOnlyError):
        s.record_verdict("GS-SIP-1", T0, {"verdict": "PASS"})
    s.backup(tmp_path / "copy.db")
    assert st.Store(tmp_path / "copy.db").verdict("GS-SIP-1") == {"verdict": "FAIL"}


def test_store_made_on_one_thread_works_on_another(tmp_path):
    """27 Oct live: the bridge builds GS on its main thread and steps it on the gs-engine thread; sqlite3's
    same-thread check made every GS call fail (ProgrammingError), so GS sat the day out."""
    import threading
    from gs.store import Store
    st = Store(tmp_path / "gs.db")
    out = []
    t = threading.Thread(target=lambda: out.append(st.con.execute("select 1").fetchone()[0]))
    t.start(); t.join()
    assert out == [1]
