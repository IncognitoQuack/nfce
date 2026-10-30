"""Write an Upstox-format sample NIFTY chain for offline demos:  python tests/make_sample_chain.py"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from conftest import make_payload  # noqa: E402

call = {25000: (4_200_000, 3_900_000, 112.0), 25100: (5_100_000, 3_600_000, 64.0), 25200: (6_800_000, 5_200_000, 31.0)}
put = {25000: (3_900_000, 3_100_000, 98.0), 24900: (5_600_000, 4_200_000, 57.0), 24800: (6_100_000, 5_500_000, 28.0)}
out = Path(__file__).resolve().parent.parent / "data" / "sample_nifty_chain.json"
out.parent.mkdir(exist_ok=True)
out.write_text(json.dumps(make_payload(spot=25012.35, call=call, put=put, iv=11.8), indent=1))
print(f"wrote {out}")
