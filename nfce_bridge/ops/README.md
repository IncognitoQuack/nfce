# Operator scripts (22 Oct 2026)
Run them from `nfce_bridge/` with `PYTHONPATH=. .venv/bin/python ops/<script>`. None of them places orders.

| Script | What it does |
|---|---|
| `reply.py "text" <chat_id>` | Sends a plain Telegram message as the bot (token from `.env`) |
| `watch.py [HH:MM]` | Watches `/health`, the battery and new Telegram notes. Exits with a reason code: 2 health, 3 battery, 4 new message |
| `collect.py <out.db> [HH:MM]` | Each minute, records the full quote (last, volume, OI, 5-level depth) of every F&O stock, its future and the NIFTY future |
| `pull1m.py <out_dir> <day> ...` | Downloads 1-minute candles for every F&O stock (equity + future), the index spots and futures, and VIX |
| `pull3m_fo.py <out_dir> <old hist3m>` | Downloads 3-minute history from 2022-01 for every F&O stock (about 1 stock a minute at the rate limit) |
| `day_study.py` | The after-close study: MAE/MFE, recovery after the stop, groupings, the ₹1 Cr view, the live variants V0–V4 |

`day_study.py` writes its trade table to the session scratchpad; change the path at the top of the file if needed.
