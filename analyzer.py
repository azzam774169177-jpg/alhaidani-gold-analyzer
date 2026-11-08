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
        return {"signal": "WAIT", "reason": "لا توجد بيانات سوق"}

    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)

    close = data["Close"].dropna()
    if len(close) < 60:
        return {"signal": "WAIT", "reason": "بيانات غير كافية"}

    ema20 = close.ewm(span=20).mean()
    ema50 = close.ewm(span=50).mean()

    price = float(close.iloc[-1])
    e20 = float(ema20.iloc[-1])
    e50 = float(ema50.iloc[-1])

    signal = "WAIT"
    if price > e20 > e50:
        signal = "BUY"
    elif price < e20 < e50:
        signal = "SELL"

    return {
        "symbol": "XAUUSD",
        "data_source": "GC=F - Gold Futures (ليس السعر الفوري)",
        "signal": signal,
        "price": round(price, 2),
        "ema20": round(e20, 2),
        "ema50": round(e50, 2),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "notice": "تحليل تجريبي وليس توصية مضمونة"
    }

try:
    result = analyze()
except Exception as error:
    result = {"signal": "WAIT", "error": str(error)}

Path("signal.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2),
    encoding="utf-8"
)

print(json.dumps(result, ensure_ascii=False, indent=2))
