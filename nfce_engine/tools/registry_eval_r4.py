"""Score registered experiment R4 from the bridge database.

  python tools/registry_eval_r4.py --db ../nfce_bridge/data/nfce.db
"""
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.registry_r4 import judge_r4  # noqa: E402


def pairs(db: Path) -> tuple[list[tuple[float, float]], list[str]]:
    rows = sqlite3.connect(db).execute(
        "SELECT e.net_pts / e.r_pts, r.net_pts / r.r_pts, substr(e.opened, 1, 10) FROM paper_trades e JOIN paper_trades r "
        "ON e.sid = r.sid AND e.book = 'executable' AND r.book = 'r4' "
        "WHERE e.status = 'CLOSED' AND r.status = 'CLOSED' AND e.r_pts > 0 AND r.r_pts > 0").fetchall()
    return [(a, b) for a, b, _ in rows], [d for _, _, d in rows]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", type=Path, required=True)
    pr, days = pairs(ap.parse_args().db)
    print(judge_r4(pr, days).text())
