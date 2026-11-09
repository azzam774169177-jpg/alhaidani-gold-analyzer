# Telegram Gold Signals and Automatic Results Journal

This repository sends validated `signal.json` updates to Telegram and monitors published trade levels for TP/SL outcomes.

## Required GitHub Actions secrets

In **Settings → Secrets and variables → Actions → New repository secret**, add:

- `TELEGRAM_BOT_TOKEN`: the newly rotated BotFather token. Never use the token exposed in chat.
- `TELEGRAM_CHAT_ID`: the destination Telegram group chat ID.

The bot must be added to the group and permitted to send messages.

## Run

Open **Actions → Telegram Gold Signals → Run workflow** for a manual run. Scheduled runs are configured every 5 minutes.

## Automatic TP/SL monitoring

- Reads `signal.json` and validates direction, entry, stop, targets, source and timestamps.
- Gets one-minute GC=F OHLC bars from Yahoo Finance's chart endpoint.
- Tracks each distinct BUY/SELL setup and reports TP1, TP2, TP3, stop-loss and ambiguous same-candle outcomes.
- If one 1-minute candle touches both the next target and stop-loss, it marks the result **ambiguous** rather than guessing which came first.
- Daily report is sent in Yemen time; weekly and monthly reports summarize the preceding period.
- State and trade history are persisted in `.telegram-state.json` by the workflow.

## Important market-data and accounting limitations

The current signal source is `GC=F` (gold futures), not spot `XAUUSD`. The monitor also uses GC=F one-minute bars, which can be delayed, unavailable during market closures, or differ from a broker's XAUUSD quote. It is not a broker execution record.

The scheduled workflow checks at 5-minute intervals, so a brief price touch between checks can be missed if the provider does not retain the corresponding one-minute bar. When quotes are stale or unavailable, the bot alerts and does not classify a trade as a win or loss.

The report shows price difference in USD per troy ounce for completed TP3/stop outcomes. It does not convert this into broker "points", because point conventions differ between brokers. If a target is reached and price later returns to stop, the result is marked mixed; exact net P&L requires the user's partial-close percentages and stop adjustment rules.

The bot only reports market observations. It does not execute trades and does not guarantee outcomes or provide a guaranteed trading recommendation.
