import os
import hmac
import logging
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import MetaTrader5 as mt5

app = Flask(__name__)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("alhaidani-mt5-bridge")

WEBHOOK_SECRET = os.environ.get("WEBHOOK_SECRET", "")
MT5_PATH = os.environ.get("MT5_PATH") or None
MT5_LOGIN = int(os.environ.get("MT5_LOGIN", "0"))
MT5_PASSWORD = os.environ.get("MT5_PASSWORD", "")
MT5_SERVER = os.environ.get("MT5_SERVER", "")
SYMBOL = os.environ.get("TRADE_SYMBOL", "XAUUSD")
DEFAULT_VOLUME = float(os.environ.get("DEFAULT_VOLUME", "0.01"))
MAX_VOLUME = float(os.environ.get("MAX_VOLUME", "0.01"))
ALLOW_LIVE = os.environ.get("ALLOW_LIVE_TRADING", "false").lower() == "true"
MAGIC = int(os.environ.get("MAGIC_NUMBER", "7112026"))

def connect():
    kwargs = {}
    if MT5_PATH:
        kwargs["path"] = MT5_PATH
    if MT5_LOGIN and MT5_PASSWORD and MT5_SERVER:
        kwargs.update(login=MT5_LOGIN, password=MT5_PASSWORD, server=MT5_SERVER)
    if not mt5.initialize(**kwargs):
        raise RuntimeError(f"MT5 initialize failed: {mt5.last_error()}")
    info = mt5.account_info()
    if info is None:
        mt5.shutdown()
        raise RuntimeError("MT5 account is not logged in")
    if info.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL and not ALLOW_LIVE:
        mt5.shutdown()
        raise PermissionError("Live account blocked. Test on demo; explicitly review ALLOW_LIVE_TRADING first.")
    return info

@app.get("/health")
def health():
    return jsonify(status="ok", service="Alhaidani MT5 Bridge", utc=datetime.now(timezone.utc).isoformat())

@app.post("/signal")
def signal():
    if not WEBHOOK_SECRET:
        return jsonify(error="WEBHOOK_SECRET is not configured"), 503
    supplied = request.headers.get("X-Bridge-Secret", "")
    if not hmac.compare_digest(supplied, WEBHOOK_SECRET):
        return jsonify(error="unauthorized"), 401
    data = request.get_json(silent=True) or {}
    action = str(data.get("action", "")).upper()
    symbol = str(data.get("symbol", SYMBOL)).upper()
    if action not in ("BUY", "SELL"):
        return jsonify(error="action must be BUY or SELL"), 400
    if symbol != SYMBOL.upper():
        return jsonify(error=f"only {SYMBOL} is enabled"), 400
    try:
        volume = float(data.get("volume", DEFAULT_VOLUME))
        sl = float(data["sl"])
        tp = float(data["tp"])
    except (KeyError, TypeError, ValueError):
        return jsonify(error="provide numeric sl and tp prices; volume is optional"), 400
    if volume <= 0 or volume > MAX_VOLUME:
        return jsonify(error=f"volume must be between >0 and {MAX_VOLUME}"), 400

    try:
        account = connect()
        try:
            if not mt5.symbol_select(symbol, True):
                return jsonify(error=f"cannot select {symbol}", detail=str(mt5.last_error())), 400
            tick = mt5.symbol_info_tick(symbol)
            spec = mt5.symbol_info(symbol)
            if tick is None or spec is None:
                return jsonify(error="symbol quote/spec unavailable"), 503
            order_type = mt5.ORDER_TYPE_BUY if action == "BUY" else mt5.ORDER_TYPE_SELL
            price = tick.ask if action == "BUY" else tick.bid
            if (action == "BUY" and not (sl < price < tp)) or (action == "SELL" and not (tp < price < sl)):
                return jsonify(error="SL/TP do not match direction or current market price", price=price), 400
            request_data = {
                "action": mt5.TRADE_ACTION_DEAL,
                "symbol": symbol,
                "volume": volume,
                "type": order_type,
                "price": price,
                "sl": sl,
                "tp": tp,
                "deviation": 20,
                "magic": MAGIC,
                "comment": "Alhaidani bridge",
                "type_time": mt5.ORDER_TIME_GTC,
                "type_filling": spec.filling_mode,
            }
            check = mt5.order_check(request_data)
            if check is None or check.retcode != 0:
                return jsonify(error="order_check rejected", detail=str(check), last_error=str(mt5.last_error())), 400
            result = mt5.order_send(request_data)
            if result is None:
                return jsonify(error="order_send returned no result", last_error=str(mt5.last_error())), 502
            if result.retcode not in (mt5.TRADE_RETCODE_DONE, mt5.TRADE_RETCODE_PLACED):
                return jsonify(error="broker rejected order", retcode=result.retcode, comment=result.comment), 502
            log.info("Order accepted: ticket=%s action=%s symbol=%s volume=%s", result.order, action, symbol, volume)
            return jsonify(status="accepted", ticket=result.order, deal=result.deal, action=action,
                           symbol=symbol, volume=volume, price=result.price, sl=sl, tp=tp,
                           account_mode="REAL" if account.trade_mode == mt5.ACCOUNT_TRADE_MODE_REAL else "DEMO")
        finally:
            mt5.shutdown()
    except PermissionError as exc:
        return jsonify(error=str(exc)), 403
    except Exception as exc:
        log.exception("Bridge execution failed")
        return jsonify(error=str(exc)), 500

if __name__ == "__main__":
    # Bind only to localhost by default. Put behind a firewall/reverse proxy for remote access.
    app.run(host=os.environ.get("BRIDGE_HOST", "127.0.0.1"),
            port=int(os.environ.get("BRIDGE_PORT", "8787")), debug=False)
