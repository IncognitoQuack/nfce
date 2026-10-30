"""NFCE-X phase 1b live features: options, order book and news, computed only from rows known at `asof`."""
import json
import math

import pandas as pd

from nfx import live_features as lf

T = lambda s: pd.Timestamp(f"2026-10-27 {s}", tz="Asia/Kolkata")  # noqa: E731


def _chain():
    rows = []
    for ts, spot, ivshift in (("09:20:00+05:30", 25000, 0.0), ("10:00:00+05:30", 25050, 1.0), ("15:00:00+05:30", 24000, 9.0)):
        for k in (24900, 25000, 25100):
            m = (k - spot) / 100
            rows.append(dict(ts=f"2026-10-27T{ts}", underlying="NIFTY", expiry="2026-11-03", spot=spot, strike=k, typ="CE",
                             iv=14 + ivshift, delta=0.5 - 0.25 * m, oi=1000))
            rows.append(dict(ts=f"2026-10-27T{ts}", underlying="NIFTY", expiry="2026-11-03", spot=spot, strike=k, typ="PE",
                             iv=16 + ivshift, delta=-0.5 - 0.25 * m, oi=1500))
    return pd.DataFrame(rows)


def test_options_use_only_rows_before_asof():
    f = lf.option_features(_chain(), T("10:05"))
    assert f["opt_iv_atm"] == 16.0 and f["opt_iv_chg_day"] == 1.0          # the 15:00 row (+9) is ignored
    assert f["opt_skew_25d"] == 2.0 and f["opt_pcr_oi"] == 1.5
    assert lf.option_features(_chain(), T("09:00")) == {}


def test_options_skip_the_expiring_contract():
    ch = _chain()
    today = ch.copy()
    today["expiry"], today["iv"] = "2026-10-27", 60.0                # same-day expiry: distorted IV, must be ignored
    f = lf.option_features(pd.concat([ch, today]), T("10:05"))
    assert f["opt_iv_atm"] == 16.0


def test_options_accept_naive_recorder_times():
    ch = _chain()
    ch["ts"] = ch["ts"].str.replace("+05:30", "", regex=False)       # the chain recorder writes naive IST times
    assert lf.option_features(ch, T("10:05"))["opt_iv_atm"] == 16.0


def test_book_imbalance_and_spread():
    d = {"buy": [{"quantity": 300, "price": 100.0}] + [{"quantity": 100, "price": 99.9 - i / 10} for i in range(4)],
         "sell": [{"quantity": 100, "price": 100.1}] + [{"quantity": 100, "price": 100.2 + i / 10} for i in range(4)]}
    f = lf.book_features(json.dumps(d))
    assert f["book_imb_l1"] == 0.5 and f["book_imb_l2_5"] == 0.0
    assert math.isclose(f["book_spread_bp"], 0.1 / 100.05 * 1e4)
    assert lf.book_features("not json") == {} and lf.book_features(json.dumps({"buy": [], "sell": []})) == {}


def test_news_ignores_later_filings():
    news = pd.DataFrame([dict(symbol="RECLTD", fno=1, disseminated="2026-10-27 08:10:00", category="Financial Results",
                              text="Results"),
                         dict(symbol="RECLTD", fno=1, disseminated="2026-10-27 13:00:00", category="General", text="x")])
    f = lf.news_features(news, "RECLTD", T("10:10"))
    assert f["news_results"] == 1.0 and f["news_in_market_hours"] == 0.0 and f["news_count_day"] == 1.0
    assert math.isclose(f["news_mins_since"], 120.0)
    assert math.isnan(lf.news_features(news, "INFY", T("10:10"))["news_mins_since"])
