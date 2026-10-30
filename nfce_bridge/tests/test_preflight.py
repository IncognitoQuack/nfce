"""Preflight self-check (22 Oct evening): catches a misaligned system before the morning start."""
from datetime import datetime, timedelta
from types import SimpleNamespace

import pytest

from bridge.preflight import ledger_problems, registry_problems
from bridge.providers import IST


def test_the_ledger_must_reconcile_to_the_cash(settings):
    from bridge.account import Account
    from bridge.options import OptionLeg
    from bridge.store import Store
    from conftest import FakeTelegram
    st = Store(settings.db_path)
    b = SimpleNamespace(store=st, provider=None, tg=FakeTelegram(), _fresh=lambda *a, **k: True)
    a = Account(b, 500_000, name="5L")
    t = datetime(2026, 10, 22, 10, 0, tzinfo=IST)
    a.consider(t, "s1", OptionLeg("NIFTY", "OPT", 23000, "CE", "2026-10-27", 59.0, 60.0, 0.5, 65, 45.0, 75, 90, 105, ""),
               "SPOT", 1, [23070, 23130, 23160, 23190], 0.0, "x")
    assert ledger_problems(st, {"5L": 500_000}) == []
    st.kv_set("account_5L_cash", a.cash + 100)                         # cash no longer matches the ledger
    assert "5L" in ledger_problems(st, {"5L": 500_000})[0]


def test_frozen_file_hashes_are_checked_against_the_registry(tmp_path):
    root = tmp_path
    (root / "nfce_bridge" / "bridge").mkdir(parents=True)
    f = root / "nfce_bridge" / "bridge" / "rules.py"
    f.write_text("x = 1\n")
    import hashlib
    h = hashlib.sha256(f.read_bytes()).hexdigest()
    (root / "REGISTRY.md").write_text(f"### Frozen files (v3, SHA-256)\n| nfce_bridge/bridge/rules.py | `{h}` |\n\n"
                                      f"## Frozen files (18 Oct) SUPERSEDED\n| nfce_bridge/bridge/rules.py | `{'0' * 64}` |\n")
    assert registry_problems(root) == []
    f.write_text("x = 2\n")
    assert "rules.py" in registry_problems(root)[0]
