"""Data loading, validation and provenance for the research tools (review L03 and the roadmap's data manifest).

Every CSV the tools read is normalised (lower-case columns, Asia/Kolkata index) and validated before use:
  structural errors raise DataError: no rows, missing OHLC columns or values, duplicate or unsorted timestamps,
  high below max(open, close) or low above min(open, close), intraday timestamps off the bar grid;
  session problems are reported: bars outside 09:15-15:30 IST (raise unless drop_off_session=True, e.g. the
  Muhurat session) and short sessions (fewer bars than the median session).
A MANIFEST.json next to the files records SHA-256, rows, range, sessions, source and the requested period, so every
result can name exactly which data produced it. load_csv refuses a file whose hash no longer matches its manifest.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

IST = "Asia/Kolkata"
OHLC = ["open", "high", "low", "close"]
SESSION_OPEN, SESSION_CLOSE = "09:15", "15:30"


class DataError(ValueError):
    pass


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def normalise(d: pd.DataFrame, name: str) -> pd.DataFrame:
    if d is None or len(d) == 0:
        raise DataError(f"{name}: no rows (empty download, rate limit or wrong symbol)")
    d = d.copy()
    d.columns = [str(c).lower().replace(" ", "_") for c in d.columns]
    idx = pd.DatetimeIndex(pd.to_datetime(d.index, utc=True))
    d.index = idx.tz_convert(IST)
    return d


def validate(d: pd.DataFrame, name: str, interval_min: int | None, drop_off_session: bool = False) -> dict:
    """Raise DataError on structural problems; return a summary. interval_min None or >= 1440 = daily bars."""
    missing = [c for c in OHLC if c not in d.columns]
    if missing:
        raise DataError(f"{name}: missing columns {missing}")
    if d[OHLC].isna().any().any():
        raise DataError(f"{name}: {int(d[OHLC].isna().any(axis=1).sum())} rows with missing OHLC values")
    vals = d[OHLC].to_numpy(dtype=float)
    bad = ~np.isfinite(vals).all(axis=1) | (vals <= 0).any(axis=1)          # FIX (review round 3, M07)
    if bad.any():
        raise DataError(f"{name}: {int(bad.sum())} rows with infinite, zero or negative prices, first {d.index[bad][0]}")
    if getattr(d.index, "tz", None) is None:
        raise DataError(f"{name}: timestamps have no time zone")
    if d.index.has_duplicates:
        raise DataError(f"{name}: {int(d.index.duplicated().sum())} duplicate timestamps")
    if not d.index.is_monotonic_increasing:
        raise DataError(f"{name}: timestamps not sorted")
    hi_bad = d["high"] < d[["open", "close"]].max(axis=1)
    lo_bad = d["low"] > d[["open", "close"]].min(axis=1)
    if hi_bad.any():
        raise DataError(f"{name}: {int(hi_bad.sum())} bars with high below open/close, first {d.index[hi_bad][0]}")
    if lo_bad.any():
        raise DataError(f"{name}: {int(lo_bad.sum())} bars with low above open/close, first {d.index[lo_bad][0]}")
    intraday = interval_min is not None and interval_min < 1440
    dropped = 0
    if intraday:
        hm = d.index.strftime("%H:%M")
        off = (hm < SESSION_OPEN) | (hm >= SESSION_CLOSE)
        if off.any():
            if not drop_off_session:
                raise DataError(f"{name}: {int(off.sum())} bars outside the NSE session, first {d.index[off][0]} "
                                f"(pass drop_off_session=True to drop them, e.g. a Muhurat session)")
            dropped = int(off.sum())
            d.drop(index=d.index[off], inplace=True)
        mins = d.index.hour * 60 + d.index.minute - (9 * 60 + 15)
        off_grid = (mins % interval_min) != 0
        if off_grid.any():
            raise DataError(f"{name}: {int(off_grid.sum())} timestamps off the {interval_min}-minute grid, "
                            f"first {d.index[off_grid][0]}")
    days = pd.Series(d.index.normalize()).value_counts().sort_index()
    short = [str(k.date()) for k, v in days.items() if v < days.median()] if intraday else []
    return {"rows": len(d), "first": str(d.index[0]), "last": str(d.index[-1]), "sessions": int(len(days)),
            "short_sessions": short, "off_session_dropped": dropped}


def update_manifest(folder: Path, path: Path, **meta) -> dict:
    """Record (or refresh) one file's provenance in folder/MANIFEST.json."""
    folder, path = Path(folder), Path(path)
    interval = meta.get("interval", "")
    d = normalise(pd.read_csv(path, index_col=0), path.name)
    summary = validate(d, path.name, _interval_min(interval), drop_off_session=True)
    entry = {"sha256": sha256(path), **{k: summary[k] for k in ("rows", "first", "last", "sessions")},
             "short_sessions": summary["short_sessions"], "off_session_bars": summary["off_session_dropped"],
             "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"), **meta}
    mf = folder / "MANIFEST.json"
    data = json.loads(mf.read_text()) if mf.exists() else {}
    data[path.name] = entry
    mf.write_text(json.dumps(data, indent=1, sort_keys=True))
    return entry


def load_csv(path: Path, interval_min: int | None, drop_off_session: bool = True, check_manifest: bool = True):
    """Load, normalise and validate one CSV. Returns (frame, summary incl. sha256)."""
    path = Path(path)
    if not path.exists():
        raise DataError(f"{path}: not found (run tools/fetch_yahoo.py first)")
    digest = sha256(path)
    mf = path.parent / "MANIFEST.json"
    if check_manifest and mf.exists():
        rec = json.loads(mf.read_text()).get(path.name)
        if rec and rec["sha256"] != digest:
            raise DataError(f"{path.name}: SHA-256 {digest[:12]} does not match MANIFEST.json {rec['sha256'][:12]} "
                            f"(file changed after it was recorded; re-fetch or update the manifest)")
    d = normalise(pd.read_csv(path, index_col=0), path.name)
    summary = validate(d, path.name, interval_min, drop_off_session)
    return d, {**summary, "sha256": digest, "file": path.name}


def _interval_min(interval: str) -> int | None:
    s = str(interval).lower()
    if s.endswith("m") and s[:-1].isdigit():
        return int(s[:-1])
    if s.endswith("h") and s[:-1].isdigit():
        return 60 * int(s[:-1])
    return None
