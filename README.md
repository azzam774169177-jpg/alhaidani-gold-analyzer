# alhaidani-gold-analyzer

## Telegram chart-photo analyzer (rule-based, no AI)

The photo worker in `telegram_photo_bot.py` receives chart screenshots posted in a Telegram group and calls `photo_chart_analyzer.py`. It uses OpenCV colour masks and a simple pixel-trend estimate. It does **not** use a language model, paid AI API, OCR, or broker credentials.

### What it can and cannot do

- Recognizes common green and red candle colours in a screenshot.
- Reports a rough visual bias (up / down / wait) when enough coloured pixels are visible.
- Does not extract reliable price-axis values, symbol, timeframe, OHLC data, indicators, entry, stop-loss, or take-profit from arbitrary screenshots.
- Unknown themes, altered candle colours, overlays, low resolution, and cropped charts should return WAIT.
- The result is an experimental image inspection, not a trading signal or execution instruction.

### Run the Telegram photo worker

Run this as a **continuously running worker** on a host that supports Python 3.11:

```bash
pip install -r requirements.txt
export TELEGRAM_BOT_TOKEN="YOUR_TOKEN"
export TELEGRAM_ALLOWED_CHAT_ID="-1003960644699"
python telegram_photo_bot.py
```

Set secrets as environment variables in the hosting provider. Never commit a bot token to GitHub. The worker defaults to the configured `بوت تحليل الذهب XAUUSD` group (`-1003960644699`) if this variable is omitted. Set it explicitly in the host environment when deploying.

### Telegram setup

1. Add the bot to the target group and make it an administrator (or give it permission to read and reply to messages).
2. In BotFather, use `/setprivacy`, select the bot, then choose **Disable** so it can receive ordinary group photo messages. Re-add the bot to the group if Telegram requires it after changing privacy.
3. Ensure no other process is polling `getUpdates` with the same bot token. Telegram allows only one active long-polling consumer per bot token.
4. Post a clear MT5 screenshot with the candles visible.

### Hosting limitation

GitHub Actions scheduled every five minutes is not a continuously running Telegram listener. The photo worker must run on an always-on process/worker host. A free host may sleep or impose usage limits; availability is not guaranteed.

## Existing market-data pipeline

- The separate `analyzer.py` uses Yahoo Finance `XAUUSD=X` indicative spot-gold data, not Weltrade executable prices.
- `.github/workflows/telegram-gold.yml` runs on a five-minute schedule; it is not a real-time listener.
- `maintenance_notice.json` remains a hard safety lock. Do not disable it until the separate market-data pipeline is verified.
- Real Weltrade MT5 quotes require a supported Windows MT5 terminal bridge; Android MT5 does not expose the desktop Python API.
- Never place Telegram, GitHub, or trading passwords in repository files.
