# alhaidani-gold-analyzer

## AI Telegram chart-photo replies

The Render web service receives chart photos posted in the configured Telegram group, sends the image to the OpenAI Responses API, and replies to the same Telegram message in Arabic. The model may return BUY/SELL only when the screenshot gives enough readable evidence; otherwise it returns WAIT. Levels are estimates read from the screenshot, not live broker quotes or guaranteed trading advice.

### Required Render environment variables

- `TELEGRAM_BOT_TOKEN`: create/copy from BotFather; keep it only in Render Environment.
- `TELEGRAM_WEBHOOK_SECRET`: a random secret string used to authenticate Telegram webhook requests.
- `TELEGRAM_ALLOWED_CHAT_ID`: target group ID; set the actual group ID if it differs from the configured value.
- `OPENAI_API_KEY`: OpenAI API key, stored only in Render Environment (never commit it to GitHub).
- `OPENAI_MODEL`: optional; defaults to `gpt-6-astra`.

After saving environment variables, Render redeploys the service. The app configures the Telegram webhook on startup. Add the bot to the group, grant permission to read/reply, and disable BotFather privacy mode if it must receive ordinary group photos. Ensure no other webhook or polling service is using the same bot token.

### Important limitations

- The photo reply feature is separate from automated market-signal publishing.
- The model only sees the submitted screenshot and optional caption; it has no live MT5/Weltrade quote unless a separate trusted feed is integrated.
- If price labels or the setup are unclear, it should reply WAIT rather than invent levels.
- AI image analysis can be wrong. Verify every level and use strict risk management.
- GitHub Actions scheduled every five minutes is not a real-time Telegram listener; this feature uses the Render webhook service.
- The separate `analyzer.py` market-data pipeline uses Yahoo Finance indicative data, not Weltrade executable prices. The maintenance lock remains in place.
- Never put Telegram, OpenAI, GitHub, or trading passwords in repository files.
