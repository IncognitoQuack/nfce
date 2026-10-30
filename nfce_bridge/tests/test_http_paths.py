"""Exercise the real HTTP code paths (Upstox, Telegram, login) against fake servers."""
import json
import socket
import threading
import time
from pathlib import Path

import httpx
import pytest

from bridge import check_setup, upstox_login
from bridge.providers import TokenExpired, UpstoxProvider
from conftest import make_payload

ENV_KEYS = ["PROVIDER", "UPSTOX_API_KEY", "UPSTOX_API_SECRET", "UPSTOX_REDIRECT_URI", "TOKEN_FILE",
            "TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "WEBHOOK_SECRET", "DB_PATH", "MOCK_CHAIN_FILE"]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.delenv(k, raising=False)


def write_token(path: Path, valid=True):
    path.write_text(json.dumps({"access_token": "tok123", "expires_at": time.time() + (3600 if valid else -60)}))


def upstox_transport(seen, timeout=False):
    chain = make_payload(spot=25012.35)

    def handler(req: httpx.Request):
        seen.append(req)
        if timeout:
            raise httpx.ReadTimeout("simulated", request=req)
        if req.headers.get("Authorization") != "Bearer tok123":
            return httpx.Response(401, json={"status": "error"})
        if req.url.path == "/v2/option/contract":
            return httpx.Response(200, json={"status": "success", "data": [
                {"expiry": "2020-01-07", "instrument_key": "NSE_FO|1"},
                {"expiry": "2099-12-29", "instrument_key": "NSE_FO|2"},
                {"expiry": "2099-12-22", "instrument_key": "NSE_FO|3"}]})
        if req.url.path == "/v2/option/chain":
            return httpx.Response(200, json=chain)
        if req.url.path == "/v2/market-quote/quotes":
            ms = str(int(time.time() * 1000) - 2000)
            return httpx.Response(200, json={"status": "success", "data": {
                "NSE_FO:NIFTY26OCTFUT": {"instrument_token": "NSE_FO|49229", "last_price": 25110.5, "last_trade_time": ms,
                                         "depth": {"buy": [{"price": 25110.4, "quantity": 650}],
                                                   "sell": [{"price": 25110.8, "quantity": 325}]}, "oi": 1.2e7},
                "NSE_INDEX:Nifty 50": {"instrument_token": "NSE_INDEX|Nifty 50", "last_price": 25012.35,
                                       "last_trade_time": ms, "net_change": 42.1}}})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


INSTRUMENTS = [
    {"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "NIFTY", "instrument_key": "NSE_FO|49229",
     "expiry": int(time.mktime((2099, 1, 27, 15, 30, 0, 0, 0, -1)) * 1000), "lot_size": 65, "tick_size": 10.0,
     "trading_symbol": "NIFTY FUT 27 JAN 99"},
    {"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "NIFTY", "instrument_key": "NSE_FO|49999",
     "expiry": int(time.mktime((2099, 2, 24, 15, 30, 0, 0, 0, -1)) * 1000), "lot_size": 65, "tick_size": 10.0,
     "trading_symbol": "NIFTY FUT 24 FEB 99"},
    {"segment": "NSE_FO", "instrument_type": "FUT", "underlying_symbol": "NIFTY", "instrument_key": "NSE_FO|11111",
     "expiry": int(time.mktime((2020, 1, 30, 15, 30, 0, 0, 0, -1)) * 1000), "lot_size": 75, "tick_size": 5.0,
     "trading_symbol": "NIFTY FUT 30 JAN 20"},
    {"segment": "NSE_FO", "instrument_type": "CE", "underlying_symbol": "NIFTY", "instrument_key": "NSE_FO|2",
     "expiry": int(time.mktime((2099, 1, 1, 15, 30, 0, 0, 0, -1)) * 1000)},
]


@pytest.fixture
def fake_instruments(monkeypatch):
    import gzip

    from bridge import providers

    def fake_get(url, timeout=None):
        return httpx.Response(200, content=gzip.compress(json.dumps(INSTRUMENTS).encode()),
                              request=httpx.Request("GET", url))
    monkeypatch.setattr(providers.httpx, "get", fake_get)


def test_quotes_and_front_future(tmp_path, fake_instruments):
    from datetime import date
    tok = tmp_path / "tok.json"
    write_token(tok)
    p = UpstoxProvider(tok, min_interval_s=0, instruments_cache=tmp_path / "inst.json",
                       client=httpx.Client(base_url="https://api.upstox.com/v2", transport=upstox_transport([])))
    fut = p.front_future("NIFTY", date(2026, 10, 21))
    assert fut.instrument_key == "NSE_FO|49229" and fut.lot_size == 65          # nearest live FUT, not expired / not CE
    qs = p.quotes([fut.instrument_key, "NSE_INDEX|Nifty 50"])
    fq = qs["NSE_FO|49229"]
    assert fq.last_price == 25110.5 and fq.bid == 25110.4 and fq.ask == 25110.8 and abs(fq.spread - 0.4) < 1e-9
    assert fq.last_trade_time is not None and qs["NSE_INDEX|Nifty 50"].last_price == 25012.35
    assert (tmp_path / "inst.json").exists()                                    # cached for the day


def test_raw_timeouts_become_provider_errors(tmp_path):
    from bridge.providers import ProviderError
    tok = tmp_path / "tok.json"
    write_token(tok)
    p = UpstoxProvider(tok, min_interval_s=0,
                       client=httpx.Client(base_url="https://api.upstox.com/v2", transport=upstox_transport([], timeout=True)))
    with pytest.raises(ProviderError, match="ReadTimeout"):
        p.chain("X", "2099-12-22")


def test_upstox_requests_and_parsing(tmp_path):
    seen = []
    tok = tmp_path / "tok.json"
    write_token(tok)
    p = UpstoxProvider(tok, min_interval_s=0,
                       client=httpx.Client(base_url="https://api.upstox.com/v2", transport=upstox_transport(seen)))
    exp = p.nearest_expiry("NSE_INDEX|Nifty 50")
    assert exp == "2099-12-22"                                   # nearest future, not the past one
    ch = p.chain("NSE_INDEX|Nifty 50", exp)
    assert ch.spot == 25012.35 and len(ch.rows) == 21
    req = seen[-1]
    assert req.url.params["instrument_key"] == "NSE_INDEX|Nifty 50" and req.url.params["expiry_date"] == exp
    assert req.headers["Accept"] == "application/json"
    p.nearest_expiry("NSE_INDEX|Nifty 50")
    assert sum(r.url.path.endswith("/contract") for r in seen) == 1   # expiries cached for the day


def test_upstox_token_problems(tmp_path):
    tok = tmp_path / "tok.json"
    p = UpstoxProvider(tok, min_interval_s=0,
                       client=httpx.Client(base_url="https://api.upstox.com/v2", transport=upstox_transport([])))
    with pytest.raises(TokenExpired, match="no Upstox token"):
        p.chain("X", "2099-12-22")
    write_token(tok, valid=False)
    with pytest.raises(TokenExpired, match="expired"):
        p.chain("X", "2099-12-22")
    tok.write_text(json.dumps({"access_token": "wrong", "expires_at": time.time() + 3600}))
    with pytest.raises(TokenExpired, match="401"):
        p.chain("X", "2099-12-22")


def tg_transport(sent, ok=True):
    def handler(req: httpx.Request):
        if req.url.path.endswith("/getMe"):
            return httpx.Response(200, json={"ok": ok, "result": {"username": "nfce_test_bot"}, "description": "Unauthorized"})
        if req.url.path.endswith("/sendMessage"):
            sent.append(json.loads(req.content))
            return httpx.Response(200, json={"ok": True})
        if req.url.path.endswith("/getUpdates"):
            return httpx.Response(200, json={"ok": True, "result": [
                {"update_id": 1, "message": {"chat": {"id": 987654321, "first_name": "Tester"}, "text": "hi"}}]})
        return httpx.Response(404)
    return httpx.MockTransport(handler)


def env_file(tmp_path, **vals):
    base = {"UPSTOX_API_KEY": "key-abc", "UPSTOX_API_SECRET": "secret-xyz", "TELEGRAM_BOT_TOKEN": "123456:SECRETTOKEN",
            "TELEGRAM_CHAT_ID": "987654321", "WEBHOOK_SECRET": "w" * 32, "TOKEN_FILE": str(tmp_path / "tok.json")}
    base.update(vals)
    f = tmp_path / ".env"
    f.write_text("\n".join(f"{k}={v}" for k, v in base.items()) + "\n")
    return f


def test_check_setup_all_good_and_never_prints_secrets(tmp_path, capsys, fake_instruments):
    f = env_file(tmp_path)
    write_token(tmp_path / "tok.json")
    sent = []
    prov = UpstoxProvider(tmp_path / "tok.json", min_interval_s=0, instruments_cache=tmp_path / "inst.json",
                          client=httpx.Client(base_url="https://api.upstox.com/v2", transport=upstox_transport([])))
    rc = check_setup.main(["--env", str(f)], client=httpx.Client(transport=tg_transport(sent)), provider=prov)
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "All good." in out and "@nfce_test_bot" in out and "NIFTY chain 2099-12-22" in out
    assert "previous-day OI present" in out and "NIFTY FUT 27 JAN 99" in out and "basis +98.2" in out
    assert sent and sent[0]["chat_id"] == "987654321"
    for secret in ("secret-xyz", "SECRETTOKEN", "key-abc", "tok123", "w" * 32):
        assert secret not in out


def test_check_setup_reports_missing_items(tmp_path, capsys):
    f = env_file(tmp_path, UPSTOX_API_SECRET="", TELEGRAM_CHAT_ID="", WEBHOOK_SECRET="")
    rc = check_setup.main(["--env", str(f), "--no-send"], client=httpx.Client(transport=tg_transport([])))
    out = capsys.readouterr().out
    assert rc == 1
    assert "[!!] UPSTOX_API_SECRET" in out and "[!!] TELEGRAM_CHAT_ID" in out and "[!!] WEBHOOK_SECRET" in out
    assert "no Upstox token yet" in out


def test_find_chat_id(tmp_path, capsys):
    f = env_file(tmp_path, TELEGRAM_CHAT_ID="")
    assert check_setup.main(["--env", str(f), "--find-chat-id"], client=httpx.Client(transport=tg_transport([]))) == 0
    assert "TELEGRAM_CHAT_ID=987654321" in capsys.readouterr().out


def test_ensure_webhook_secret_fills_only_empty(tmp_path):
    f = tmp_path / ".env"
    f.write_text("A=1\nWEBHOOK_SECRET=\n")
    assert check_setup.ensure_webhook_secret(f)
    val = [l for l in f.read_text().splitlines() if l.startswith("WEBHOOK_SECRET=")][0].split("=", 1)[1]
    assert len(val) >= 30
    assert not check_setup.ensure_webhook_secret(f)          # second run keeps the same secret
    assert val in f.read_text()


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_login_flow_end_to_end(tmp_path, monkeypatch):
    port = free_port()
    f = env_file(tmp_path, UPSTOX_REDIRECT_URI=f"http://127.0.0.1:{port}/callback")
    orig = upstox_login.Settings.from_env
    monkeypatch.setattr(upstox_login.Settings, "from_env", classmethod(lambda cls, env_file=None: orig(f)))
    posted = {}

    def fake_post(url, headers=None, data=None, timeout=None):
        posted.update(url=url, data=data)
        return httpx.Response(200, json={"access_token": "NEWTOKEN"})

    def fake_browser(url):
        state = httpx.URL(url).params["state"]
        assert httpx.URL(url).params["client_id"] == "key-abc"

        def hit():
            for _ in range(50):
                try:
                    httpx.get(f"http://127.0.0.1:{port}/callback", params={"code": "CODE42", "state": state}, timeout=2)
                    return
                except httpx.HTTPError:
                    time.sleep(0.05)
        threading.Thread(target=hit, daemon=True).start()
        return True

    monkeypatch.setattr(upstox_login.httpx, "post", fake_post)
    monkeypatch.setattr(upstox_login.webbrowser, "open", fake_browser)
    upstox_login.main()
    saved = json.loads((tmp_path / "tok.json").read_text())
    assert saved["access_token"] == "NEWTOKEN" and saved["expires_at"] > time.time()
    assert posted["url"].endswith("/login/authorization/token")
    assert posted["data"]["code"] == "CODE42" and posted["data"]["grant_type"] == "authorization_code"
    assert (tmp_path / "tok.json").stat().st_mode & 0o777 == 0o600


def test_login_token_error_shows_upstox_reason_and_hint_not_secret(tmp_path, monkeypatch):
    """First live run: 'Token exchange failed: HTTP 401' hid Upstox's reason (UDAPI100057, a used/expired code)."""
    port = free_port()
    f = env_file(tmp_path, UPSTOX_REDIRECT_URI=f"http://127.0.0.1:{port}/callback")
    orig = upstox_login.Settings.from_env
    monkeypatch.setattr(upstox_login.Settings, "from_env", classmethod(lambda cls, env_file=None: orig(f)))
    secret = orig(f).upstox_api_secret
    monkeypatch.setattr(upstox_login.httpx, "post", lambda *a, **k: httpx.Response(
        401, json={"status": "error", "errors": [{"errorCode": "UDAPI100057", "message": "Invalid Auth code"}]}))

    def fake_browser(url):
        state = httpx.URL(url).params["state"]

        def hit():
            for _ in range(50):
                try:
                    httpx.get(f"http://127.0.0.1:{port}/callback", params={"code": "C1", "state": state}, timeout=2)
                    return
                except httpx.HTTPError:
                    time.sleep(0.05)
        threading.Thread(target=hit, daemon=True).start()
        return True
    monkeypatch.setattr(upstox_login.webbrowser, "open", fake_browser)
    with pytest.raises(SystemExit) as e:
        upstox_login.main()
    msg = str(e.value)
    assert "UDAPI100057" in msg and "Invalid Auth code" in msg and "run bash start.sh again" in msg
    assert secret and secret not in msg


def _login_with_browser(tmp_path, monkeypatch, visit, timeout_s=10):
    port = free_port()
    f = env_file(tmp_path, UPSTOX_REDIRECT_URI=f"http://127.0.0.1:{port}/callback")
    orig = upstox_login.Settings.from_env
    monkeypatch.setattr(upstox_login.Settings, "from_env", classmethod(lambda cls, env_file=None: orig(f)))
    monkeypatch.setattr(upstox_login.httpx, "post", lambda *a, **k: pytest.fail("token exchange must not run"))
    statuses = []

    def fake_browser(url):
        state = httpx.URL(url).params["state"]

        def hit():
            for path, params in visit(state):
                statuses.append(httpx.get(f"http://127.0.0.1:{port}{path}", params=params, timeout=2).status_code)
        threading.Thread(target=hit, daemon=True).start()
        return True
    monkeypatch.setattr(upstox_login.webbrowser, "open", fake_browser)
    with pytest.raises(SystemExit) as e:
        upstox_login.main(timeout_s=timeout_s)
    return str(e.value), statuses


def test_login_error_redirect_and_wrong_path(tmp_path, monkeypatch):
    msg, statuses = _login_with_browser(tmp_path, monkeypatch, lambda st: [
        ("/favicon.ico", {}), ("/callback", {"state": "forged", "code": "X"}),
        ("/callback", {"state": st, "error": "access_denied"})])
    for _ in range(40):                                  # the visiting thread records the last reply after main() exits
        if len(statuses) == 3:
            break
        time.sleep(0.05)
    assert "access_denied" in msg and statuses[:2] == [404, 400]
    assert not (tmp_path / "tok.json").exists()


def test_login_times_out_instead_of_hanging(tmp_path, monkeypatch):
    t = time.monotonic()
    msg, _ = _login_with_browser(tmp_path, monkeypatch, lambda st: [], timeout_s=2)
    assert "No Upstox login within" in msg and time.monotonic() - t < 10
