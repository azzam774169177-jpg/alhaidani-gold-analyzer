import json
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd
import yfinance as yf

# PRO multi-timeframe engine. Analysis/signals only; never places broker orders.
SYMBOL = "GC=F"  # Indicative COMEX futures proxy, not broker-executable XAUUSD.
SOURCE = "GC=F - Yahoo Finance COMEX gold futures indicative quote (not broker feed)"
MIN_BARS = 60
SWING_WINDOW = 2
MAX_EMA_EXTENSION_ATR = 1.25
BUY_EXHAUSTION_RSI = 68
SELL_EXHAUSTION_RSI = 32


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
        "updated_utc": now.isoformat(), "execution_mode": "SIGNALS_ONLY",
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
    data = data[["Open", "High", "Low", "Close"]].copy()
    data = data.apply(pd.to_numeric, errors="coerce").dropna()
    if data.index.tz is None:
        data.index = data.index.tz_localize("UTC")
    else:
        data.index = data.index.tz_convert("UTC")
    return data.sort_index()


def resample_ohlc(data, rule, now):
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
    prior_e20 = float(ema20.iloc[-4])
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


def atr_value(candles, period=14):
    previous = candles["Close"].shift(1)
    true_range = pd.concat([
        candles["High"] - candles["Low"],
        (candles["High"] - previous).abs(),
        (candles["Low"] - previous).abs()
    ], axis=1).max(axis=1)
    value = float(true_range.rolling(period).mean().iloc[-1])
    if not pd.notna(value) or value <= 0:
        raise ValueError("تعذر حساب ATR صالح")
    return value


def confirmed_swings(candles, window=SWING_WINDOW, lookback=80):
    """Return the latest confirmed fractal swing high/low; right-side bars confirm pivots."""
    sample = candles.tail(lookback)
    highs, lows = [], []
    for i in range(window, len(sample) - window):
        high = float(sample["High"].iloc[i])
        low = float(sample["Low"].iloc[i])
        left_high = sample["High"].iloc[i-window:i]
        right_high = sample["High"].iloc[i+1:i+window+1]
        left_low = sample["Low"].iloc[i-window:i]
        right_low = sample["Low"].iloc[i+1:i+window+1]
        if high > float(left_high.max()) and high >= float(right_high.max()):
            highs.append((sample.index[i], high))
        if low < float(left_low.min()) and low <= float(right_low.min()):
            lows.append((sample.index[i], low))
    return (highs[-1][1] if highs else None, lows[-1][1] if lows else None)


def structure_break(candles, direction):
    swing_high, swing_low = confirmed_swings(candles)
    close = float(candles["Close"].iloc[-1])
    if direction == "BUY":
        broken = swing_high is not None and close > swing_high
        level = swing_high
    else:
        broken = swing_low is not None and close < swing_low
        level = swing_low
    return {"confirmed": bool(broken), "level": round(level, 2) if level is not None else None}


def detect_liquidity_sweep(candles):
    """Detect a wick beyond a confirmed swing followed by a close back inside."""
    prior = candles.iloc[:-1]
    swing_high, swing_low = confirmed_swings(prior)
    last = candles.iloc[-1]
    close = float(last["Close"])
    low = float(last["Low"])
    high = float(last["High"])
    bullish = swing_low is not None and low < swing_low and close > swing_low
    bearish = swing_high is not None and high > swing_high and close < swing_high
    return {
        "bullish_sweep": bool(bullish), "bearish_sweep": bool(bearish),
        "swept_low": round(swing_low, 2) if bullish else None,
        "swept_high": round(swing_high, 2) if bearish else None,
        "note": "رصد ذيل كاسر عاد وأغلق داخل البنية؛ إشارة مساعدة وليست إثباتاً لنية صانع السوق."
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

    # Yahoo timestamps M15 candles by opening time; discard any still-forming candle.
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
    details = {"M15": m15_info, "H1": h1_info, "H4": h4_info}

    m15_rsi = m15_info["rsi14"]
    if m15_rsi is None:
        return wait_result("تعذر حساب زخم RSI على M15", m15_info["candle_time"], details)

    directions = [h4_info["trend"], h1_info["trend"], m15_info["trend"]]
    normal_alignment = len(set(directions)) == 1 and directions[0] in ("BUY", "SELL")
    candidate = None
    reversal_mode = False
    structure = {"confirmed": False, "level": None}

    if normal_alignment:
        candidate = directions[0]
    elif h1_info["trend"] == m15_info["trend"] and h1_info["trend"] in ("BUY", "SELL"):
        # Permit an early reversal against H4 only after H1+M15 agree and M15 breaks
        # its latest confirmed swing in the new direction (CHoCH-style confirmation).
        candidate = h1_info["trend"]
        structure = structure_break(candles, candidate)
        reversal_mode = h4_info["trend"] != candidate
        if reversal_mode and not structure["confirmed"]:
            details["reversal_check"] = {
                "candidate": candidate, "structure_break": structure,
                "status": "WAITING_FOR_CONFIRMED_STRUCTURE_BREAK"
            }
            return wait_result(
                "احتمال انعكاس مبكر، لكن لم يتأكد كسر البنية السعرية على M15؛ ننتظر ولا نطارد الاتجاه القديم.",
                m15_info["candle_time"], details
            )
    else:
        return wait_result(
            "تعارض أو عدم اكتمال توافق H1 وM15؛ لا توجد إشارة مؤكدة.",
            m15_info["candle_time"], details
        )

    momentum_ok = (
        50 <= m15_rsi <= 68 if candidate == "BUY"
        else 32 <= m15_rsi <= 50
    )
    if not momentum_ok:
        return wait_result(
            f"الزخم غير مناسب أو قد يكون مستنفداً لاتجاه {candidate} (RSI={m15_rsi:.1f})؛ تم منع مطاردة الحركة.",
            m15_info["candle_time"], details
        )

    atr = atr_value(candles)
    price = float(candles["Close"].iloc[-1])
    ema20 = float(candles["Close"].ewm(span=20, adjust=False).mean().iloc[-1])
    extension_atr = abs(price - ema20) / atr
    if extension_atr > MAX_EMA_EXTENSION_ATR:
        details["anti_chase"] = {
            "extension_atr": round(extension_atr, 2),
            "maximum_allowed_atr": MAX_EMA_EXTENSION_ATR,
            "status": "BLOCKED_OVEREXTENDED"
        }
        return wait_result(
            f"تم منع إشارة {candidate}: السعر ابتعد عن EMA20 بمقدار {extension_atr:.2f} ATR؛ لا نطارد الحركة.",
            m15_info["candle_time"], details
        )

    recent = candles.iloc[-21:-1]
    support = float(recent["Low"].min())
    resistance = float(recent["High"].max())
    if candidate == "BUY":
        room = resistance - price
        if room < 0.6 * atr:
            return wait_result("المقاومة قريبة؛ المساحة المتاحة لا تبرر شراءً جديداً.", m15_info["candle_time"], details)
        entry = price
        stop = min(entry - 1.5 * atr, support - 0.1 * atr)
        risk = entry - stop
        targets = [entry + risk, entry + 2 * risk, entry + 3 * risk]
    else:
        room = price - support
        if room < 0.6 * atr:
            return wait_result("الدعم قريب؛ المساحة المتاحة لا تبرر بيعاً جديداً.", m15_info["candle_time"], details)
        entry = price
        stop = max(entry + 1.5 * atr, resistance + 0.1 * atr)
        risk = stop - entry
        targets = [entry - risk, entry - 2 * risk, entry - 3 * risk]

    rounded = lambda value: round(float(value), 2)
    details["anti_chase"] = {
        "extension_atr": round(extension_atr, 2),
        "maximum_allowed_atr": MAX_EMA_EXTENSION_ATR,
        "status": "PASSED"
    }
    details["structure"] = {
        "mode": "REVERSAL_CONFIRMED" if reversal_mode else "TREND_CONTINUATION",
        "break": structure if reversal_mode else structure_break(candles, candidate)
    }
    liquidity = detect_liquidity_sweep(candles)
    details["liquidity_sweep"] = liquidity
    # Technical quality score, not a statistical probability of winning.
    score_parts = {
        "توافق الاتجاهات": 25 if normal_alignment else 20,
        "زخم RSI": 20,
        "عدم مطاردة السعر": 15,
        "البنية السعرية": 15 if (not reversal_mode or structure["confirmed"]) else 5,
        "المساحة إلى المستوى المقابل": 15,
        "رصد سحب السيولة المتوافق": 10 if (
            (candidate == "BUY" and liquidity["bullish_sweep"]) or
            (candidate == "SELL" and liquidity["bearish_sweep"])
        ) else 5
    }
    quality_score = min(100, sum(score_parts.values()))
    details["quality_score"] = {
        "score": quality_score, "components": score_parts,
        "meaning": "درجة جودة فنية تقديرية من 100 وليست احتمال نجاح إحصائياً."
    }
    if quality_score < 65:
        return wait_result(
            f"جودة الإشارة {quality_score}/100 أقل من الحد الأدنى 65؛ تم منع نشرها.",
            m15_info["candle_time"], details
        )
    reason = (
        "تأكيد انعكاس مبكر: توافق H1 وM15 مع كسر بنية M15، "
        "وزخم ومسافة سعرية مقبولان."
        if reversal_mode else
        "توافق H4 وH1 وM15 مع زخم غير مستنفد، وعدم ابتعاد مفرط عن EMA20."
    )
    return {
        "symbol": "XAUUSD", "market_proxy": SYMBOL, "data_source": SOURCE,
        "timeframe": "M15/H1/H4", "signal": candidate, "reason": reason,
        "price": rounded(price), "entry": rounded(entry),
        "stop_loss": rounded(stop),
        "take_profit_1": rounded(targets[0]),
        "take_profit_2": rounded(targets[1]),
        "take_profit_3": rounded(targets[2]),
        "atr_14": rounded(atr), "support_20": rounded(support),
        "resistance_20": rounded(resistance), "rsi14_m15": round(m15_rsi, 2),
        "ema20_extension_atr": round(extension_atr, 2),
        "quality_score": quality_score, "quality_components": score_parts,
        "liquidity_sweep": liquidity,
        "signal_mode": "REVERSAL_CONFIRMED" if reversal_mode else "TREND_CONTINUATION",
        "timeframes": details, "candle_time": candles.index[-1].isoformat(),
        "updated_utc": now.isoformat(), "execution_mode": "SIGNALS_ONLY",
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
