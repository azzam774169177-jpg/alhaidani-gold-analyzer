import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf


def analyze():
    data = yf.download(
        "GC=F",
        period="5d",
        interval="15m",
        progress=False,
        auto_adjust=False
    )

    if data.empty:
        return {"symbol": "XAUUSD", "signal": "WAIT", "reason": "لا توجد بيانات سوق"}

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    required = {"High", "Low", "Close"}
    if not required.issubset(data.columns):
        return {"symbol": "XAUUSD", "signal": "WAIT", "reason": "بيانات OHLC غير مكتملة"}

    candles = data[["High", "Low", "Close"]].dropna()
    if len(candles) < 60:
        return {"symbol": "XAUUSD", "signal": "WAIT", "reason": "بيانات غير كافية"}

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
            signal = "BUY"
            reason = "اتجاه صاعد وفق المتوسطات المتحركة"
            entry = price
            stop_loss = entry - 1.5 * atr_value
            risk = entry - stop_loss
            targets = [entry + risk, entry + 2 * risk, entry + 3 * risk]
        elif price < e20 < e50:
            signal = "SELL"
            reason = "اتجاه هابط وفق المتوسطات المتحركة"
            entry = price
            stop_loss = entry + 1.5 * atr_value
            risk = stop_loss - entry
            targets = [entry - risk, entry - 2 * risk, entry - 3 * risk]

    rounded = lambda value: round(value, 2) if value is not None else None

    return {
        "symbol": "XAUUSD",
        "data_source": "GC=F - COMEX Gold Futures proxy (Yahoo Finance; not spot XAUUSD)",
        "timeframe": "15m",
        "signal": signal,
        "reason": reason,
        "price": round(price, 2),
        "entry": rounded(entry),
        "stop_loss": rounded(stop_loss),
        "take_profit_1": rounded(targets[0]),
        "take_profit_2": rounded(targets[1]),
        "take_profit_3": rounded(targets[2]),
        "atr_14": round(atr_value, 2) if pd.notna(atr_value) else None,
        "ema20": round(e20, 2),
        "ema50": round(e50, 2),
        "candle_time": str(candles.index[-1]),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "تحليل تجريبي؛ المستويات محسوبة من ATR وليست توصية مضمونة. تحقق من سعر وسيطك قبل التنفيذ."
    }


try:
    result = analyze()
except Exception as error:
    result = {
        "symbol": "XAUUSD",
        "data_source": "XAUUSD=X - Spot Gold indicative quote (Yahoo Finance)",
        "signal": "WAIT",
        "error": str(error),
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }

Path("signal.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps(result, ensure_ascii=False, indent=2))
