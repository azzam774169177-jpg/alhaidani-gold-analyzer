import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

# PRO multi-timeframe signal engine. Signals only: no broker order execution.
SYMBOL = "GC=F"  # Indicative COMEX futures proxy, not broker-executable XAUUSD.
SOURCE = "GC=F - Yahoo Finance COMEX gold futures indicative quote (not broker feed)"
MIN_BARS = 60


def utc_now():
    return datetime.now(timezone.utc)


def wait_result(reason, candle_time=None, details=None):
    now = utc_now()
    result = {
        "symbol": "XAUUSD", "market_proxy": SYMBOL, "data_source": SOURCE,
        "timeframe": "M15/H1/H4", "signal": "WAIT", "reason": reason, "price": 0,
        "entry": None, "stop_loss": None, "take_profit_1": None,
        "take_profit_2": None, "take_profit_3": None,
        "candle_time": candle_time or now.isoformat(),
        "updated_utc": now.isoformat(),
        "execution_mode": "SIGNALS_ONLY",
        "notice": "لا يتم فتح صفقات آلياً. السعر استرشادي لعقود COMEX GC=F وليس سعراً تنفيذياً من وسيطك."
    }
    if details:
        result["timeframes"] = details
    return result


def normalize_columns(data):
    if isinstance(data.columns, pd.MultiIndex):
        data.columns = data.columns.get_level_values(0)
    required = {"Open", "High", "Low", "Close"}
    if not required.issubset(data.columns):
        raise ValueError("بيانات OHLC غير مكتملة")
    data = data[list(required)].copy()
    data = data.apply(pd.to_numeric, errors="coerce").dropna()
    if data.index.tz is None:
        data.index = data.index.tz_localize("UTC")
    else:
        data.index = data.index.tz_convert("UTC")
    return data.sort_index()


def resample_ohlc(data, rule, now):
    # Build higher timeframes only from completed M15 candles.
    aggregated = data.resample(rule, label="right", closed="left", origin="epoch").agg({
        "Open": "first", "High": "max", "Low": "min", "Close": "last"
    }).dropna()
    boundary = pd.Timestamp(now).floor(rule)
    return aggregated.loc[aggregated.index <= boundary]


def indicators(candles, name):
    if len(candles) < MIN_BARS:
        raise ValueError(f"بيانات {name} غير كافية ({len(candles)} شمعة)")
    close = candles["Close"]
    ema20 = close.ewm(span=20, adjust=False).mean()
    ema50 = close.ewm(span=50, adjust=False).mean()
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/14, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/14, adjust=False).mean()
    rs = gain / loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))
    last = candles.iloc[-1]
    e20, e50 = float(ema20.iloc[-1]), float(ema50.iloc[-1])
    price = float(last["Close"])
    prior_e20 = float(ema20.iloc[-4]) if len(ema20) >= 4 else e20
    if price > e20 > e50 and e20 > prior_e20:
        trend = "BUY"
    elif price < e20 < e50 and e20 < prior_e20:
        trend = "SELL"
    else:
        trend = "NEUTRAL"
    return {
        "trend": trend, "price": price, "ema20": e20, "ema50": e50,
        "rsi14": float(rsi.iloc[-1]) if pd.notna(rsi.iloc[-1]) else None,
        "candle_time": candles.index[-1].isoformat()
    }


def analyze():
    now = utc_now()
    raw = yf.download(
        SYMBOL, period="60d", interval="15m", progress=False,
        auto_adjust=False, threads=False
    )
    if raw.empty:
        return wait_result("مصدر GC=F لم يُرجع بيانات حديثة")
    candles = normalize_columns(raw)

    # Yahoo timestamps 15m candles by their opening time; discard a still-forming candle.
    candles = candles.loc[candles.index + pd.Timedelta(minutes=15) <= pd.Timestamp(now)]
    if len(candles) < MIN_BARS:
        return wait_result("بيانات M15 المكتملة غير كافية")

    age = (pd.Timestamp(now) - candles.index[-1]).total_seconds()
    if age > 30 * 60 or age < 0:
        return wait_result(f"آخر شمعة M15 غير حديثة ({int(age)} ثانية)")

    h1 = resample_ohlc(candles, "1h", now)
    h4 = resample_ohlc(candles, "4h", now)
    m15_info = indicators(candles, "M15")
    h1_info = indicators(h1, "H1")
    h4_info = indicators(h4, "H4")

    # Momentum confirmation on the entry timeframe.
    m15_rsi = m15_info["rsi14"]
    if m15_rsi is None:
        return wait_result("تعذر حساب زخم RSI على M15", m15_info["candle_time"])
    if m15_info["trend"] == "BUY":
        momentum_ok = 50 <= m15_rsi <= 72
    elif m15_info["trend"] == "SELL":
        momentum_ok = 28 <= m15_rsi <= 50
    else:
        momentum_ok = False

    details = {"M15": m15_info, "H1": h1_info, "H4": h4_info}
    directions = [h4_info["trend"], h1_info["trend"], m15_info["trend"]]
    if len(set(directions)) != 1 or directions[0] not in ("BUY", "SELL"):
        return wait_result(
            "تعارض أو عدم اكتمال توافق الاتجاه بين H4 وH1 وM15؛ لا توجد إشارة.",
            m15_info["candle_time"], details
        )
    if not momentum_ok:
        return wait_result(
            f"الاتجاه متوافق لكن الزخم غير مؤكد على M15 (RSI={m15_rsi:.1f}).",
            m15_info["candle_time"], details
        )

    # ATR(14) on M15 for volatility-adjusted risk levels.
    prev_close = candles["Close"].shift(1)
    true_range = pd.concat([
        candles["High"] - candles["Low"],
        (candles["High"] - prev_close).abs(),
        (candles["Low"] - prev_close).abs()
    ], axis=1).max(axis=1)
    atr = float(true_range.rolling(14).mean().iloc[-1])
    price = float(candles["Close"].iloc[-1])
    if not pd.notna(atr) or atr <= 0:
        return wait_result("تعذر حساب ATR صالح على M15", m15_info["candle_time"], details)

    # Recent support/resistance from the 20 completed candles before the current one.
    recent = candles.iloc[-21:-1]
    support = float(recent["Low"].min())
    resistance = float(recent["High"].max())
    if directions[0] == "BUY":
        room = resistance - price
        if room < 0.6 * atr:
            return wait_result("المقاومة قريبة؛ نسبة المساحة المتاحة لا تبرر إشارة شراء.", m15_info["candle_time"], details)
        entry = price
        stop = min(entry - 1.5 * atr, support - 0.1 * atr)
        risk = entry - stop
        targets = [entry + risk, entry + 2 * risk, entry + 3 * risk]
        signal = "BUY"
    else:
        room = price - support
        if room < 0.6 * atr:
            return wait_result("الدعم قريب؛ نسبة المساحة المتاحة لا تبرر إشارة بيع.", m15_info["candle_time"], details)
        entry = price
        stop = max(entry + 1.5 * atr, resistance + 0.1 * atr)
        risk = stop - entry
        targets = [entry - risk, entry - 2 * risk, entry - 3 * risk]
        signal = "SELL"

    rounded = lambda value: round(float(value), 2)
    return {
        "symbol": "XAUUSD", "market_proxy": SYMBOL, "data_source": SOURCE,
        "timeframe": "M15/H1/H4", "signal": signal,
        "reason": "توافق اتجاه H4 وH1 وM15 مع تأكيد زخم RSI ومساحة كافية حتى مستوى الدعم/المقاومة.",
        "price": rounded(price), "entry": rounded(entry),
        "stop_loss": rounded(stop),
        "take_profit_1": rounded(targets[0]),
        "take_profit_2": rounded(targets[1]),
        "take_profit_3": rounded(targets[2]),
        "atr_14": rounded(atr), "support_20": rounded(support),
        "resistance_20": rounded(resistance),
        "rsi14_m15": round(m15_rsi, 2),
        "timeframes": details,
        "candle_time": candles.index[-1].isoformat(),
        "updated_utc": now.isoformat(),
        "execution_mode": "SIGNALS_ONLY",
        "notice": "إشارة تحليلية فقط ولا تفتح صفقة آلياً. GC=F سعر عقود COMEX استرشادي وقد يختلف عن XAUUSD لدى وسيطك؛ تحقق من السعر وإدارة المخاطر."
    }


try:
    result = analyze()
except Exception as error:
    result = wait_result("تعذر التحليل الآمن: " + str(error))

Path("signal.json").write_text(
    json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
)
print(json.dumps(result, ensure_ascii=False, indent=2))
