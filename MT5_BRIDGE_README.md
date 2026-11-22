# Alhaidani MT5 Bridge (Windows VPS)

This is a separate Windows-hosted execution bridge. The existing Telegram analyzer in this repository analyzes user-submitted chart screenshots; it does **not** produce live quotes or automatic trading signals. The bridge only executes a separately authenticated JSON signal sent to `POST /signal`.

## Safety defaults
- Live-account execution is disabled unless `ALLOW_LIVE_TRADING=true` is explicitly set.
- Start with a Weltrade demo account.
- Default and maximum volume are both 0.01 lots.
- Only the configured symbol (default XAUUSD) is accepted.
- Every order must include numeric stop-loss and take-profit **price levels**.
- Never expose port 8787 publicly without HTTPS, firewall restrictions, and a strong secret. The server binds to localhost by default.
- Do not put credentials or secrets in GitHub. Store them only in the Windows VPS environment.

## Install on a Windows VPS
1. Install the Weltrade MetaTrader 5 desktop terminal and sign in to a **demo** account.
2. Install 64-bit Python 3.11, then in PowerShell:
   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements-bridge.txt
   ```
3. Set the environment variables from `.env.example` in the Windows service/session. Set `MT5_PATH` to the actual `terminal64.exe` path. Set demo login/server/password locally.
4. Run:
   ```powershell
   python mt5_bridge.py
   ```
5. Check `http://127.0.0.1:8787/health`.

## Send a test signal
Use the VPS itself (PowerShell) and replace the secret. The SL/TP values below are examples only; use valid levels for the current quote and broker's symbol specification.
```powershell
$headers = @{ "X-Bridge-Secret" = "YOUR_LONG_SECRET" }
$body = @{ action="BUY"; symbol="XAUUSD"; volume=0.01; sl=2000.00; tp=2100.00 } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8787/signal -Headers $headers -ContentType "application/json" -Body $body
```

## Signal contract
```json
{ "action": "BUY", "symbol": "XAUUSD", "volume": 0.01, "sl": 2000.00, "tp": 2100.00 }
```
Use `SELL` for sell orders. SL/TP are absolute instrument prices, not pips or points. The analyzer is not connected to this endpoint yet; a separate authenticated sender must be implemented and tested before automation.

## Important platform limitation
The official `MetaTrader5` Python package requires a Windows environment with the MT5 terminal installed and running. This bridge is not intended to run on a generic Linux Railway worker.
