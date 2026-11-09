# Telegram Gold Signals Setup

This repository sends validated `signal.json` updates to a Telegram group using GitHub Actions.

## Required GitHub Actions secrets

In **Settings → Secrets and variables → Actions → New repository secret**, add:

- `TELEGRAM_BOT_TOKEN`: the newly rotated BotFather token. Do not use the token previously exposed in chat.
- `TELEGRAM_CHAT_ID`: the target Telegram group chat ID (usually a negative integer for a supergroup).

## Telegram setup

1. Revoke the token that was exposed and create a new token with BotFather.
2. Add the bot to the target group and allow it to send messages.
3. Obtain the group chat ID securely (for example, use a temporary getUpdates check after sending a message in the group; do not post the bot token publicly).
4. Add both GitHub secrets above.

## Run and verify

Open **Actions → Telegram Gold Signals → Run workflow** to send a test report.
The scheduled check runs every 5 minutes (GitHub Actions scheduled workflows have a 5-minute minimum interval).

The notifier:
- validates all required fields in `signal.json`;
- checks `updated_utc` and `candle_time` independently;
- sends on signal-file changes and a daily Yemen-time report;
- alerts on a new data-access/validation error and on stale-data status transitions;
- explicitly identifies `GC=F` as futures, not spot XAUUSD.

A file update is not evidence that the candle itself is fresh. This bot reports data; it does not guarantee trade outcomes or execute trades.
