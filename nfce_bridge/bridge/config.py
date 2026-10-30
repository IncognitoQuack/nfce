"""Settings loaded from environment variables and an optional .env file (no extra dependency)."""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

# Spot index keys as used by the Upstox option-chain and quote APIs. NIFTY and BANKNIFTY are the ones the
# backtests covered; check the others against Upstox's instrument list before relying on them.
DEFAULT_UNDERLYINGS = {
    "NIFTY": "NSE_INDEX|Nifty 50",
    "BANKNIFTY": "NSE_INDEX|Nifty Bank",
    "FINNIFTY": "NSE_INDEX|Nifty Fin Service",
    "MIDCPNIFTY": "NSE_INDEX|NIFTY MID SELECT",
    "SENSEX": "BSE_INDEX|SENSEX",
}
# `underlying_symbol` of the futures contracts in the Upstox instruments file, and the futures tick size.
FUTURES_SYMBOL = {"NIFTY": "NIFTY", "BANKNIFTY": "BANKNIFTY", "FINNIFTY": "FINNIFTY", "MIDCPNIFTY": "MIDCPNIFTY",
                  "SENSEX": "SENSEX"}
# Executable-entry spread limits in index points (reject the paper entry when the book is wider).
MAX_SPREAD_PTS = {"NIFTY": 3.0, "BANKNIFTY": 8.0, "FINNIFTY": 4.0, "MIDCPNIFTY": 3.0, "SENSEX": 12.0}


def load_dotenv(path: Path) -> None:
    """Minimal KEY=VALUE loader. Existing environment variables win."""
    if not path.is_file():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass
class Settings:
    provider: str = "upstox"                       # "upstox" or "mock"
    upstox_api_key: str = ""
    upstox_api_secret: str = ""
    upstox_redirect_uri: str = "http://127.0.0.1:8765/callback"
    token_file: Path = ROOT / "data" / "upstox_token.json"
    instruments_cache: Path = ROOT / "data" / "instruments_NSE.json"
    mock_chain_file: Path | None = None
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_allowed_user_ids: set[str] = field(default_factory=set)   # empty = only the chat id itself
    telegram_extra_chat_ids: set[str] = field(default_factory=set)     # the owner's other private chats (commands)
    telegram_admin_chat_ids: set[str] = field(default_factory=set)     # empty = the main and extra chats are admins
    assistant_relay: bool = False                   # "@admin:" notes are also read by an assistant (Claude) when on
    webhook_secret: str = ""
    db_path: Path = ROOT / "data" / "nfce.db"
    # polling
    quote_seconds: int = 15                         # futures + spot + VIX quote poll (one API call)
    poll_seconds: int = 60                          # option-chain poll (heavier)
    poll_underlyings: list[str] = field(default_factory=lambda: ["NIFTY"])
    engine_underlyings: list[str] = field(default_factory=list)     # NFCE signals computed by the bridge itself
    engine_timeframes: tuple = (5, 15)              # minutes; 3 is allowed (Upstox 3m candles), untested historically
    scanner: bool = False                           # F&O stock scanner (top gainers/losers, volume surges)
    stock_engine: bool = False                      # 3-minute NFCE signals for every F&O stock
    gs: bool = False                                # GS research engine (paper, own book; needs STOCK_ENGINE=on)
    gs_db: Path = ROOT / "data" / "gs.db"           # its own append-only store, never nfce.db
    account_capital: float = 0.0                    # paper ACCOUNT starting capital (0 = off); owner: 2,00,000
    accounts: dict = field(default_factory=dict)    # name -> capital, e.g. {"2L": 200000, "5L": 500000}
    account_strategies: dict = field(default_factory=dict)   # name -> base|concentrated|wide|confirm|cluster
    account_risk_pct: float = 1.0                   # risk per trade, % of equity
    account_daily_loss_pct: float = 3.0             # no new entries after this day loss
    account_max_open: int = 4
    early_risk: float = 0.0                         # EARLY mode failed its test (evidence/stock3m_result.md): no trades
    stock_signal_risk: float = 0.25                 # stock 3m signals failed as futures: small live experiment only
    scanner_mode: str = "watchlist"                 # owner 21 Oct 11:45: gainers are to WATCH, not to buy; "trade" = old
    scanner_times: tuple = ("09:21", "09:30", "10:15", "11:15", "13:15")   # 09:21/09:30 = opening watchlist
    option_legs: bool = True                        # 1-ITM option entry/SL/targets for every signal (and paper book)
    # analytics / rules
    window: int = 5                                 # ATM +/- N strikes for PCR and writing checks
    pcr_doi_veto: float = 0.7                       # BUY veto below this; SELL veto above 1/this
    # data freshness and execution realism
    max_quote_age_s: int = 90                       # last trade older than this = stale (frozen feed / holiday)
    max_chain_age_s: int = 180                      # older chain data is treated as unavailable
    max_clock_skew_s: int = 30                      # a bar time this far in the FUTURE = clock problem, no entry
    paper_lots: int = 10                            # whole lots per paper trade (4/3/3 at T1/T2/T3, like the strategy)
    max_signal_delay_s: int = 120                   # signal bar close -> receipt; older = no executable entry
    max_gap_s: int = 75                             # gap between quote observations that counts as an outage
    extra_slippage_ticks: int = 2                   # added to the bid/ask touch in the executable book
    max_spread_pts: dict[str, float] = field(default_factory=lambda: dict(MAX_SPREAD_PTS))
    # risk (spec section 6: stop for the day after 2 losses or -2R)
    daily_max_losses: int = 2
    daily_max_loss_r: float = 2.0
    max_trades_per_day: int = 4
    last_entry_hhmm: int = 1445
    square_off_hhmm: int = 1515
    # webhook hygiene
    max_body_bytes: int = 16_384
    max_requests_per_minute: int = 60
    underlyings: dict[str, str] = field(default_factory=lambda: dict(DEFAULT_UNDERLYINGS))
    futures_symbol: dict[str, str] = field(default_factory=lambda: dict(FUTURES_SYMBOL))

    @classmethod
    def from_env(cls, env_file: Path | None = None) -> "Settings":
        load_dotenv(env_file or ROOT / ".env")
        e = os.environ.get
        s = cls()
        s.provider = e("PROVIDER", s.provider).lower()
        s.upstox_api_key = e("UPSTOX_API_KEY", "")
        s.upstox_api_secret = e("UPSTOX_API_SECRET", "")
        s.upstox_redirect_uri = e("UPSTOX_REDIRECT_URI", s.upstox_redirect_uri)
        if e("TOKEN_FILE"):
            s.token_file = Path(e("TOKEN_FILE"))
        if e("MOCK_CHAIN_FILE"):
            s.mock_chain_file = Path(e("MOCK_CHAIN_FILE"))
        s.telegram_bot_token = e("TELEGRAM_BOT_TOKEN", "")
        s.telegram_chat_id = e("TELEGRAM_CHAT_ID", "")
        s.telegram_allowed_user_ids = {x.strip() for x in e("TELEGRAM_ALLOWED_USER_IDS", "").split(",") if x.strip()}
        s.telegram_extra_chat_ids = {x.strip() for x in e("TELEGRAM_EXTRA_CHAT_IDS", "").split(",") if x.strip()}
        s.telegram_admin_chat_ids = {x.strip() for x in e("TELEGRAM_ADMIN_CHAT_IDS", "").split(",") if x.strip()}
        s.assistant_relay = e("ASSISTANT_RELAY", "off").lower() in ("on", "1", "true", "yes")
        s.webhook_secret = e("WEBHOOK_SECRET", "")
        if e("DB_PATH"):
            s.db_path = Path(e("DB_PATH"))
        s.quote_seconds = max(5, int(e("QUOTE_SECONDS", s.quote_seconds)))
        s.poll_seconds = max(15, int(e("POLL_SECONDS", s.poll_seconds)))
        if e("POLL_UNDERLYINGS"):
            s.poll_underlyings = [x.strip().upper() for x in e("POLL_UNDERLYINGS").split(",") if x.strip()]
        if e("ENGINE_UNDERLYINGS"):
            s.engine_underlyings = [x.strip().upper() for x in e("ENGINE_UNDERLYINGS").split(",") if x.strip()]
        if e("ENGINE_TIMEFRAMES"):
            s.engine_timeframes = tuple(sorted({int(x) for x in e("ENGINE_TIMEFRAMES").split(",")
                                                if x.strip() in ("3", "5", "15")}))
        s.scanner = e("SCANNER", "off").lower() in ("on", "1", "true", "yes")
        s.stock_engine = e("STOCK_ENGINE", "off").lower() in ("on", "1", "true", "yes")
        s.gs = e("GS", "off").lower() in ("on", "1", "true", "yes")
        if e("GS_DB"):
            s.gs_db = Path(e("GS_DB"))
        s.account_capital = float(e("ACCOUNT_CAPITAL", "0") or 0)
        if e("ACCOUNTS"):                                  # e.g. ACCOUNTS=5L:500000,CONC:500000:concentrated
            for x in e("ACCOUNTS").split(","):
                parts = [y.strip() for y in x.split(":")]
                if len(parts) >= 2:
                    s.accounts[parts[0]] = float(parts[1])
                    s.account_strategies[parts[0]] = parts[2] if len(parts) > 2 and parts[2] else "base"
        elif s.account_capital > 0:
            s.accounts = {"2L": s.account_capital}
        s.account_risk_pct = float(e("ACCOUNT_RISK_PCT", s.account_risk_pct))
        s.account_daily_loss_pct = float(e("ACCOUNT_DAILY_LOSS_PCT", s.account_daily_loss_pct))
        s.account_max_open = int(e("ACCOUNT_MAX_OPEN", s.account_max_open))
        mode = e("SCANNER_MODE", "watchlist").lower()       # sell (23 Oct): trade the losers, only watch the gainers
        s.scanner_mode = mode if mode in ("trade", "sell") else "watchlist"
        s.option_legs = e("OPTION_LEGS", "on").lower() in ("on", "1", "true", "yes")
        s.window = int(e("ATM_WINDOW", s.window))
        s.pcr_doi_veto = float(e("PCR_DOI_VETO", s.pcr_doi_veto))
        for name in ("max_quote_age_s", "max_chain_age_s", "max_signal_delay_s", "max_gap_s",
                     "extra_slippage_ticks", "daily_max_losses", "max_trades_per_day", "paper_lots",
                     "max_clock_skew_s"):
            if e(name.upper()):
                setattr(s, name, int(e(name.upper())))
        if e("DAILY_MAX_LOSS_R"):
            s.daily_max_loss_r = float(e("DAILY_MAX_LOSS_R"))
        s.paper_lots = max(1, s.paper_lots)
        return s
