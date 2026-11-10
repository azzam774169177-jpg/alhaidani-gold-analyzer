# alhaidani-gold-analyzer

Gold market analysis and Telegram signal pipeline for XAUUSD.

## Current status

- Analysis reference: Yahoo Finance `XAUUSD=X` spot-gold indicative feed.
- This is **not** a live Weltrade quote and is not an execution price.
- GitHub Actions is scheduled every 5 minutes; the workflow can also be run manually.
- `maintenance_notice.json` is a hard safety lock. While `signals_paused` is `true`, the notifier exits without publishing any trade.
- Trade execution is not implemented. The system only analyzes and sends Telegram alerts when explicitly enabled.

## Weltrade MT5 integration

A genuine broker quote requires MetaTrader 5 running and logged into the user's Weltrade account on a supported Windows machine. Android MT5 does not expose the desktop Python integration used for this bridge. Do not enter or commit trading passwords, Telegram tokens, or GitHub tokens into repository files.

Until a Windows MT5 bridge is installed, treat all Yahoo Finance prices as indicative only and do not execute from them.
