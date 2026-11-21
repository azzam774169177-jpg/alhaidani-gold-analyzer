# Alhaidani MT5 Bridge — Stage 1 (safe receiver)

This branch adds a MetaTrader 5 Expert Advisor that polls the repository's signal.json every 5 seconds and displays the received signal in the MT5 chart.

## Important current limitations

- Monitoring only: the EA intentionally has no order-placement code. It cannot open, modify, or close trades.
- The analyzer currently publishes execution_mode: SIGNALS_ONLY.
- The analyzer currently identifies GC=F (Yahoo/COMEX futures) as its market proxy, not a live executable Weltrade XAUUSD quote.
- The current sample signal is WAIT. These conditions must not be used to trigger a real account order.
- A phone can be used to edit and publish these files on GitHub, but the EA must run inside MT5 Desktop on Windows. MT5 Android cannot load Expert Advisors.

## Install on a Windows MT5 terminal

1. Download MQL5/Experts/AlhaidaniBridgeReceiver.mq5 from this branch.
2. In MT5 Desktop, choose File → Open Data Folder.
3. Copy the file into MQL5/Experts/.
4. Open MetaEditor, compile the EA, then attach it to an XAUUSD chart.
5. In MT5, open Tools → Options → Expert Advisors and allow WebRequest for:
   https://raw.githubusercontent.com
6. Keep Algo Trading disabled; this EA does not need it.

## Next engineering stages

1. Replace the indicative GC=F input with a timestamped quote from the user's actual broker feed.
2. Define and test a strict signal schema, symbol mapping, point/digit conversion, and stale-signal rejection.
3. Add demo-only order execution with explicit limits, duplicate-signal protection, and a kill switch.
4. Test on a Weltrade demo account before considering any live account.

Never commit broker passwords, investor passwords, API keys, Telegram bot tokens, or private SSH keys to this repository.
