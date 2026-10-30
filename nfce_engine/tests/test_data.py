import json
import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.data import DataError, load_csv, normalise, update_manifest, validate  # noqa: E402


def bars(times, o=100.0, h=101.0, low=99.0, c=100.5, v=10.0, tz="Asia/Kolkata"):
    idx = pd.DatetimeIndex(pd.to_datetime(times)).tz_localize(tz)
    return pd.DataFrame({"Open": o, "High": h, "Low": low, "Close": c, "Volume": v}, index=idx)


HOURLY = ["09:15", "10:15", "11:15", "12:15", "13:15", "14:15", "15:15"]


def hourly(*days):
    return bars([f"{d} {t}" for d in days for t in HOURLY])


def test_empty_response_fails_clearly_before_any_timezone_work():
    """Review L03: a rate-limited Yahoo call returns an empty frame; it used to crash in tz_convert."""
    with pytest.raises(DataError, match="no rows"):
        normalise(pd.DataFrame(), "^NSEI 60m")


def test_structural_errors_are_rejected():
    d = normalise(hourly("2026-10-12", "2026-10-13"), "x")
    with pytest.raises(DataError, match="duplicate"):
        validate(pd.concat([d, d.iloc[:1]]).sort_index(), "x", 60)
    with pytest.raises(DataError, match="not sorted"):
        validate(d.iloc[::-1], "x", 60)
    bad = d.copy()
    bad.iloc[3, bad.columns.get_loc("high")] = 99.5          # high below the close
    with pytest.raises(DataError, match="high below"):
        validate(bad, "x", 60)
    nan = d.copy()
    nan.iloc[2, nan.columns.get_loc("close")] = float("nan")
    with pytest.raises(DataError, match="missing"):
        validate(nan, "x", 60)
    with pytest.raises(DataError, match="columns"):
        validate(d.drop(columns=["low"]), "x", 60)


def test_session_integrity_is_reported_not_hidden():
    d = normalise(pd.concat([hourly("2026-10-12", "2026-10-13", "2026-10-14"),
                             bars(["2026-10-15 09:15", "2026-10-15 10:15"]),          # short session
                             bars(["2026-10-16 18:15"])]), "x")                      # off-session (e.g. Muhurat)
    with pytest.raises(DataError, match="outside the NSE session"):
        validate(d, "x", 60)
    s = validate(d, "x", 60, drop_off_session=True)
    assert s["off_session_dropped"] == 1 and s["sessions"] == 4
    assert s["short_sessions"] == ["2026-10-15"]
    assert s["first"].startswith("2026-10-12") and s["rows"] == 23


def test_off_grid_timestamps_are_rejected():
    d = normalise(bars(["2026-10-12 09:15", "2026-10-12 09:47"]), "x")
    with pytest.raises(DataError, match="grid"):
        validate(d, "x", 15)


def test_manifest_hash_is_checked_on_load(tmp_path):
    f = tmp_path / "NSEI_60m.csv"
    hourly("2026-10-12", "2026-10-13").to_csv(f)
    update_manifest(tmp_path, f, symbol="^NSEI", interval="60m", requested="730d", source="Yahoo Finance (yfinance)")
    m = json.loads((tmp_path / "MANIFEST.json").read_text())["NSEI_60m.csv"]
    assert len(m["sha256"]) == 64 and m["rows"] == 14 and m["sessions"] == 2 and m["requested"] == "730d"
    d, summary = load_csv(f, 60)
    assert summary["sha256"] == m["sha256"] and list(d.columns[:4]) == ["open", "high", "low", "close"]
    f.write_text(f.read_text().replace("100.5", "100.6", 1))
    with pytest.raises(DataError, match="SHA-256"):
        load_csv(f, 60)
