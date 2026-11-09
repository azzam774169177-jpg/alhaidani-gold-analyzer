import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

SYMBOL = "GC=F"  # COMEX gold futures proxy; not the broker's XAUUSD quote
SOURCE = "GC=F - COMEX Gold Futures via Yahoo Finance (indicative proxy, not Weltrade)"


def wait_result(reason):
    now = datetime.now(timezone.utc).isoformat()
    return {
        "symbol": "XAUUSD", "market_proxy": SYMBOL, "data_source": SOURCE,
        "timeframe": "15m", "signal": "WAIT", "reason": reason, "price": 0,
        "entry": None, "stop_loss": None, "take_profit_1": None,
        "take_profit_2": None, "take_profit_3": None,
        "candle_time": now, "updated_utc": now
    }


def analyze():
    data = yf.download(
        SYMBOL, period="5d", interval="15m", progress=False,
        auto_adjust=False, threads=False
    )
    if data.empty:
        return wait_result("مصدر GC=F لم يُرجع بيانات؛ لن نرسل صفقة قديمة")

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    required = {"High", "Low", "Close"}
    if not required.issubset(data.columns):
        return wait_result("بيانات OHLC غير مكتملة من مصدر GC=F")

    candles = data[["High", "Low", "Close"]].dropna()
    if len(candles) < 60:
        return wait_result("بيانات غير كافية للتحليل")

    # Reject stale candles even if the download endpoint returns cached history.
    candle_index = candles.index[-1]
    candle_dt = candle_index.to_pydatetime()
    if candle_dt.tzinfo is None:
        candle_dt = candle_dt.replace(tzinfo=timezone.utc)
    else:
        candle_dt = candle_dt.astimezone(timezone.utc)
    candle_age = (datetime.now(timezone.utc) - candle_dt).total_seconds()
    if candle_age > 30 * 60 or candle_age < -60:
        return wait_result(f"آخر شمعة قديمة ({int(candle_age)} ثانية)؛ ننتظر بيانات حديثة")

    close, high, low = candles["Close"], candles["High"], candles["Low"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    previous_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - previous_close).abs(), (low - previous_close).abs()],
        axis=1
    ).max(axis=1)
    atr_value = float(true_range.rolling(14).mean().iloc[-1])
    price = float(close.iloc[-1])
    e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])

    signal, entry, stop_loss = "WAIT", None, None
    targets = [None, None, None]
    reason = "لا يوجد توافق واضح بين السعر والمتوسطات"

    if pd.notna(atr_value) and atr_value > 0:
        if price > e20 > e50:
            signal, reason = "BUY", "اتجاه صاعد: السعر أعلى EMA20 وEMA20 أعلى EMA50"
            entry = price
            stop_loss = entry - 1.5 * atr_value
            risk = entry - stop_loss
            targets = [entry + risk, entry + 2 * risk, entry + 3 * risk]
        elif price < e20 < e50:
            signal, reason = "SELL", "اتجاه هابط: السعر أسفل EMA20 وEMA20 أسفل EMA50"
            entry = price
            stop_loss = entry + 1.5 * atr_value
            risk = stop_loss - entry
            targets = [entry - risk, entry - 2 * risk, entry - 3 * risk]

    rounded = lambda value: round(value, 2) if value is not None else None
    return {
        "symbol": "XAUUSD", "market_proxy": SYMBOL, "data_source": SOURCE,
        "timeframe": "15m", "signal": signal, "reason": reason,
        "price": round(price, 2), "entry": rounded(entry),
        "stop_loss": rounded(stop_loss),
        "take_profit_1": rounded(targets[0]),
        "take_profit_2": rounded(targets[1]),
        "take_profit_3": rounded(targets[2]),
        "atr_14": round(atr_value, 2) if pd.notna(atr_value) else None,
        "ema20": round(e20, 2), "ema50": round(e50, 2),
        "candle_time": candle_dt.isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "تحليل آلي تجريبي على عقد الذهب الآجل GC=F؛ قد يختلف عن سعر XAUUSD لدى Weltrade. تحقق من السعر قبل التنفيذ."
    }


try:
    result = analyze()
except Exception as error:
    result = wait_result("تعذر التحليل: " + str(error))

Path("signal.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))
