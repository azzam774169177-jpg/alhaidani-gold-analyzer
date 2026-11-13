# alhaidani-gold-analyzer

## Telegram XAUUSD chart-photo analyzer (Railway worker)

This repository runs a continuously running Telegram long-polling worker. Members send a chart screenshot to the bot in the configured group (or directly in a private chat); the worker sends the image to the OpenAI Responses API and replies in Arabic with BUY, SELL, or WAIT.

The analyzer only sees the submitted screenshot and optional caption. It does not receive live MT5/Weltrade quotes. Levels are estimates from the image, may be wrong, and are not guaranteed trading advice. It must return WAIT rather than invent unreadable prices or levels. This worker does not publish automatic market signals or place trades.

## Deploy on Railway

1. Create a Railway project and choose **Deploy from GitHub repo**.
2. Select `azzam774169177-jpg/alhaidani-gold-analyzer`.
3. Railway should build the included Dockerfile. Run it as a worker; no public domain or web service is required.
4. In the Railway service, open **Variables** and add:
   - `TELEGRAM_BOT_TOKEN`: token from BotFather.
   - `OPENAI_API_KEY`: OpenAI API key.
   - `TELEGRAM_ALLOWED_CHAT_ID`: target Telegram group ID (default in code is `-1003960644699`; set the actual ID if different).
   - `OPENAI_MODEL`: optional; defaults to `gpt-4.1-mini`.
5. Deploy/redeploy and check the deployment logs for: `Telegram XAUUSD photo-analysis worker started.`
6. Add the bot to the group and grant permission to read/reply. If it must receive ordinary group photos, disable BotFather privacy mode. The bot also accepts photos sent in a private chat.

Important: this worker calls Telegram `deleteWebhook` at startup because Telegram does not allow getUpdates polling and a webhook to operate at the same time for one bot token. Stop any old Render service using the same bot token. Never commit API keys or bot tokens to GitHub.

## Runtime and safety

- Railway must keep this service running as a worker; do not configure it as a scheduled task.
- OpenAI image analysis requires a valid API key and a model available to that API account that supports image input.
- If the OpenAI model is unavailable, update `OPENAI_MODEL` to an image-capable model enabled for the account.
- AI chart analysis can be wrong. Verify every level and apply independent risk management.