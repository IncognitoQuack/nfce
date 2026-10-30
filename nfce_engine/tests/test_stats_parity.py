"""The cost model must reproduce the Phase 2 numbers exactly (NIFTY1! 5m, base variant, TradingView ledger)."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from nfce.engine import Trade  # noqa: E402
from nfce.stats import summarize  # noqa: E402

NIFTY_5_BASE = (
    "29743495,S,82,1,24196.0,37.46,28.67,Q,58;29746465,S,80,0,23934.2,21.49,-21.49,S,2;29752380,L,92,0,24025.0,27.95,0,Q,9;"
    "29754970,L,86,0,24287.0,47.82,33.29,Q,67;29758005,L,76,0,24448.8,24.82,9.93,B,30;29762410,L,68,0,24661.5,22.77,-22.77,S,8;"
    "29765185,S,68,0,24648.0,39.24,51.01,B,26;29775285,S,84,0,24365.0,20.87,-20.87,S,4;29785270,S,85,0,24107.7,24.9,-24.9,S,15;"
    "29786685,L,86,0,24280.8,22.64,-22.64,S,14;29795295,L,80,0,24564.0,41.71,-41.71,S,5;29796980,S,68,0,24324.9,41.84,18.9,Q,17;"
    "29802495,S,67,0,24180.0,31.37,-31.37,S,24;29808265,L,82,0,24067.8,39.95,15.98,B,29;29812605,S,75,0,23916.8,25.22,32.79,B,39;"
    "29837055,S,82,0,23233.0,43.82,83.26,3,49;29845725,L,66,0,22880.0,40.04,-40.04,S,4;29852900,L,74,0,22718.0,45.94,-45.94,S,3;"
    "29857315,S,94,0,22458.0,53.79,102.2,3,32;"
)


def parse(s):
    out = []
    for t in filter(None, s.split(";")):
        f = t.split(",")
        out.append(Trade(None, f[1], float(f[2]), f[3] == "1", float(f[4]), float(f[5]), float(f[6]), f[7], int(f[8])))
    return out


def test_reproduces_phase2_numbers():
    s = summarize(parse(NIFTY_5_BASE), mintick=0.1, point_value=65)
    assert s.n == 19
    assert round(s.win * 100) == 42
    assert round(s.avg_r_gross, 2) == 0.01
    assert round(s.avg_r_net, 2) == -0.48
    assert round(s.pf, 2) == 0.57
    assert round(s.max_dd) == pytest.approx(18548, abs=1)
    assert round(s.net) == pytest.approx(-11965, abs=1)
    assert round(s.gross) == pytest.approx(6780, abs=1)
