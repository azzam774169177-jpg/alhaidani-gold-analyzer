#!/usr/bin/env python3
"""Telegram signal notifier and conservative XAUUSD TP/SL monitor."""
import hashlib
import html
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

SIGNAL_URL = "https://raw.githubusercontent.com/azzam774169177-jpg/alhaidani-gold-analyzer/main/signal.json"
QUOTE_URL = "https://query1.finance.yahoo.com/v8/finance/chart/GC%3DF?range=1d&interval=1m"
STATE_PATH = ".telegram-state.json"
REQUIRED = ["signal", "price", "entry", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3", "data_source", "candle_time", "updated_utc"]
LEVELS = ["take_profit_1", "take_profit_2", "take_profit_3"]
YEMEN = timezone(timedelta(hours=3))
MAX_QUOTE_AGE_SECONDS = 15 * 60
MAX_SIGNAL_AGE_SECONDS = 15 * 60
MAX_CANDLE_AGE_SECONDS = 30 * 60

def utc_now():
    return datetime.now(timezone.utc)

def parse_time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("وقت مفقود أو غير صالح")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("الوقت يجب أن يتضمن المنطقة الزمنية")
    return dt.astimezone(timezone.utc)

def fmt_time(dt):
    return dt.astimezone(YEMEN).strftime("%Y-%m-%d %H:%M:%S بتوقيت اليمن")

def age_text(seconds):
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} دقيقة"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} ساعة و{minutes % 60} دقيقة"
    return f"{hours // 24} يوم و{hours % 24} ساعة"

def num(value):
    return f"{float(value):.2f}"

def send_telegram(message):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("أضف TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID في GitHub Secrets")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({
        "chat_id": chat_id, "text": message, "parse_mode": "HTML",
        "disable_web_page_preview": "true"
    }).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(req, timeout=25) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        try:
            detail = json.loads(detail).get("description", detail)
        except (json.JSONDecodeError, AttributeError):
            pass
        bot_identity = "تعذر التحقق من هوية البوت"
        membership = "تعذر فحص عضوية البوت في القناة"
        try:
            check = urllib.request.urlopen(
                f"https://api.telegram.org/bot{token}/getMe", timeout=15
            )
            me = json.loads(check.read().decode("utf-8"))
            if me.get("ok"):
                bot_identity = "البوت المرتبط بالرمز: @" + me["result"].get("username", "بدون اسم مستخدم")
                bot_id = me["result"].get("id")
                member_url = "https://api.telegram.org/bot" + token + "/getChatMember?" + urllib.parse.urlencode({
                    "chat_id": chat_id, "user_id": bot_id
                })
                member_response = urllib.request.urlopen(member_url, timeout=15)
                member = json.loads(member_response.read().decode("utf-8"))
                if member.get("ok"):
                    info = member.get("result", {})
                    membership = "حالة البوت في القناة: " + str(info.get("status"))
                    if info.get("status") == "administrator":
                        membership += " | can_post_messages=" + str(info.get("can_post_messages"))
                else:
                    membership = "فشل getChatMember: " + str(member.get("description"))
        except urllib.error.HTTPError as identity_error:
            try:
                identity_body = identity_error.read().decode("utf-8", errors="replace")
                identity_detail = json.loads(identity_body).get("description", identity_body)
            except Exception:
                identity_detail = "تعذر قراءة تفاصيل رد Telegram"
            membership = f"فشل فحص Telegram API: HTTP {identity_error.code}: {identity_detail[:300]}"
        except Exception as identity_error:
            membership = f"فشل فحص الهوية/العضوية: {type(identity_error).__name__}: {identity_error}"
        raise RuntimeError(f"Telegram API HTTP {exc.code}: {detail[:500]} | {bot_identity} | {membership}") from exc
    if not result.get("ok"):
        raise RuntimeError(f"Telegram API رفض إرسال الرسالة: {result.get('description', 'سبب غير معروف')}")
    return True

def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            state = json.load(f)
            if isinstance(state, dict):
                return state
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return {
        "last_signal_key": None, "last_bar_ts": 0, "active_trades": [],
        "closed_trades": [], "last_daily_yemen_day": None,
        "last_weekly_key": None, "last_monthly_key": None,
        "last_error": None, "last_quote_warning": None
    }

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")

def fetch_json(url, label):
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 AlhaidaniGoldBot/1.0"})
    with urllib.request.urlopen(req, timeout=25) as response:
        if response.status != 200:
            raise RuntimeError(f"{label}: HTTP {response.status}")
        return json.loads(response.read().decode("utf-8"))

def fetch_quote_bars():
    payload = fetch_json(QUOTE_URL, "مصدر أسعار الذهب GC=F (عقود آجلة)")
    result = payload.get("chart", {}).get("result")
    if not result:
        error = payload.get("chart", {}).get("error")
        raise RuntimeError(f"تعذر الحصول على أسعار XAUUSD: {error}")
    item = result[0]
    timestamps = item.get("timestamp") or []
    quote = (item.get("indicators", {}).get("quote") or [{}])[0]
    bars = []
    for i, ts in enumerate(timestamps):
        try:
            op, hi, lo, cl = quote["open"][i], quote["high"][i], quote["low"][i], quote["close"][i]
            if None in (op, hi, lo, cl):
                continue
            bars.append({"ts": int(ts), "open": float(op), "high": float(hi), "low": float(lo), "close": float(cl)})
        except (IndexError, KeyError, TypeError, ValueError):
            continue
    if not bars:
        raise RuntimeError("مصدر XAUUSD لم يُرجع شموعاً صالحة")
    return bars

def validate_signal(data):
    missing = [key for key in REQUIRED if key not in data or data[key] is None or data[key] == ""]
    if missing:
        raise ValueError("حقول ناقصة: " + ", ".join(missing))
    signal = str(data["signal"]).upper()
    if signal not in ("BUY", "SELL", "WAIT"):
        raise ValueError("قيمة signal يجب أن تكون BUY أو SELL أو WAIT")
    for key in ["price", "entry", "stop_loss"] + LEVELS:
        if not isinstance(data[key], (int, float)) or isinstance(data[key], bool):
            raise ValueError(f"الحقل {key} ليس رقماً")
    updated = parse_time(data["updated_utc"])
    candle = parse_time(data["candle_time"])
    if signal == "BUY":
        valid = data["stop_loss"] < data["entry"] < data["take_profit_1"] <= data["take_profit_2"] <= data["take_profit_3"]
    elif signal == "SELL":
        valid = data["stop_loss"] > data["entry"] > data["take_profit_1"] >= data["take_profit_2"] >= data["take_profit_3"]
    else:
        valid = True
    if not valid:
        raise ValueError("ترتيب مستويات الدخول ووقف الخسارة والأهداف غير منطقي لاتجاه الإشارة")
    return signal, updated, candle

def signal_key(data, signal):
    fields = [signal, data["entry"], data["stop_loss"], data["take_profit_1"], data["take_profit_2"], data["take_profit_3"], data["candle_time"]]
    return hashlib.sha256(json.dumps(fields, ensure_ascii=False, separators=(",", ":")).encode()).hexdigest()

def direction_ar(signal):
    return {"BUY": "🟢 شراء BUY", "SELL": "🔴 بيع SELL", "WAIT": "🟡 انتظار WAIT"}[signal]

def signal_message(data, signal, updated, candle, now, quote, updated_age, candle_age):
    msg = (
        "👑 <b>أسطورة المجال | إشارة الذهب</b>\n\n"
        f"<b>الاتجاه:</b> {direction_ar(signal)}\n"
        f"💰 السعر عند النشر: <code>{num(data['price'])}</code>\n"
        f"🎯 الدخول: <code>{num(data['entry'])}</code>\n"
        f"🛑 وقف الخسارة: <code>{num(data['stop_loss'])}</code>\n"
        f"TP1: <code>{num(data['take_profit_1'])}</code>\n"
        f"TP2: <code>{num(data['take_profit_2'])}</code>\n"
        f"TP3: <code>{num(data['take_profit_3'])}</code>\n\n"
        f"📈 آخر سعر مراقَب للذهب GC=F: <code>{num(quote['close']) if quote else 'غير متاح'}</code>\n"
        f"🕒 تحديث الملف: {fmt_time(updated)} (العمر {age_text(updated_age)})\n"
        f"🕯 وقت الشمعة: {fmt_time(candle)} (العمر {age_text(candle_age)})\n"
        f"📡 المصدر: <code>{html.escape(str(data['data_source']))}</code>\n"
        "⚠️ المصدر GC=F عقود ذهب آجلة وليس سعر XAUUSD الفوري، وقد يختلف عن سعر وسيطك."
    )
    if updated_age > MAX_SIGNAL_AGE_SECONDS:
        msg += "\n⚠️ <b>تحذير: updated_utc قديم.</b>"
    if candle_age > MAX_CANDLE_AGE_SECONDS:
        msg += "\n⚠️ <b>تحذير: candle_time قديم؛ تحديث الملف لا يثبت حداثة الشمعة.</b>"
    return msg

def target_hit(trade, bar, target_index):
    level = float(trade["targets"][target_index])
    if trade["side"] == "BUY":
        return bar["high"] >= level
    return bar["low"] <= level

def stop_hit(trade, bar):
    level = float(trade["stop_loss"])
    if trade["side"] == "BUY":
        return bar["low"] <= level
    return bar["high"] >= level

def favorable_distance(trade, level):
    return (float(level) - float(trade["entry"])) * (1 if trade["side"] == "BUY" else -1)

def trade_summary_line(trade):
    side = "شراء" if trade["side"] == "BUY" else "بيع"
    return f"{side} | دخول {num(trade['entry'])} | أفضل هدف {trade.get('highest_target', 0)}/3 | الحالة: {html.escape(trade['status'])}"

def process_bar_for_trade(trade, bar, events):
    if trade.get("status") != "OPEN" or bar["ts"] <= trade.get("last_checked_bar", 0):
        return
    next_idx = int(trade.get("highest_target", 0))
    # If this one-minute candle touches the stop and any remaining target,
    # OHLC data cannot establish which price happened first: classify as ambiguous.
    any_target = any(target_hit(trade, bar, i) for i in range(next_idx, 3))
    stopped = stop_hit(trade, bar)
    if stopped and any_target:
        trade["status"] = "AMBIGUOUS_SL_AND_TP_SAME_CANDLE"
        trade["closed_at"] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        trade["close_price"] = None
        trade["ambiguous"] = True
        trade["last_checked_bar"] = bar["ts"]
        events.append(
            "⚠️ <b>نتيجة غير محسومة داخل شمعة واحدة</b>\n"
            f"الصفقة {trade['side']} دخول {num(trade['entry'])}: الشمعة لمست وقف الخسارة وهدفاً واحداً أو أكثر، "
            "ولا يمكن معرفة أيهما حدث أولاً من بيانات OHLC؛ لم نحتسبها ربحاً أو خسارة."
        )
        return
    if stopped:
        if trade.get("highest_target", 0) == 0:
            trade["status"] = "LOSS"
            outcome = "🔴 <b>ضرب وقف الخسارة قبل أي هدف</b>"
        else:
            trade["status"] = "MIXED_AFTER_TARGET"
            outcome = f"🟠 <b>وصلت الصفقة إلى TP{trade['highest_target']} ثم عادت إلى وقف الخسارة</b>"
        trade["closed_at"] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        trade["close_price"] = float(trade["stop_loss"])
        trade["result_delta"] = favorable_distance(trade, trade["stop_loss"])
        trade["last_checked_bar"] = bar["ts"]
        events.append(
            f"{outcome}\nالاتجاه: {trade['side']} | الدخول: {num(trade['entry'])} | "
            f"الاستوب: {num(trade['stop_loss'])} | أفضل هدف سابق: {trade.get('highest_target', 0)}/3\n"
            "لم نحسب صافي النقاط للنتيجة المختلطة لأن نسبة الإغلاق الجزئي غير محددة."
        )
        return
    # Multiple targets can be crossed in one candle; record every reached level.
    while trade.get("highest_target", 0) < 3:
        idx = int(trade.get("highest_target", 0))
        if not target_hit(trade, bar, idx):
            break
        idx += 1
        trade["highest_target"] = idx
        trade["target_hit_times"][str(idx)] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        target_price = trade["targets"][idx - 1]
        distance = abs(float(target_price) - float(trade["entry"]))
        events.append(
            f"🎯 <b>تم تحقيق TP{idx}</b>\n"
            f"الاتجاه: {trade['side']} | الدخول: {num(trade['entry'])} | الهدف: {num(target_price)}\n"
            f"فرق السعر من الدخول: {num(distance)}"
        )
    if trade.get("highest_target", 0) == 3:
        trade["status"] = "WIN_TP3"
        trade["closed_at"] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        trade["close_price"] = float(trade["targets"][2])
        trade["result_delta"] = favorable_distance(trade, trade["targets"][2])
        trade["last_checked_bar"] = bar["ts"]
        events.append("🏆 <b>اكتملت الصفقة عند الهدف الثالث TP3.</b>")
    else:
        trade["last_checked_bar"] = bar["ts"]

def summarize(trades, start, end, title):
    rows = [t for t in trades if t.get("closed_at") and start <= parse_time(t["closed_at"]) < end]
    wins = sum(1 for t in rows if t["status"] == "WIN_TP3")
    losses = sum(1 for t in rows if t["status"] == "LOSS")
    mixed = sum(1 for t in rows if t["status"] == "MIXED_AFTER_TARGET")
    ambiguous = sum(1 for t in rows if t["status"] == "AMBIGUOUS_SL_AND_TP_SAME_CANDLE")
    open_count = sum(1 for t in trades if t.get("status") == "OPEN")
    total = len(rows)
    decided = wins + losses
    rate = (wins / decided * 100) if decided else 0
    completed = [t for t in rows if t.get("status") in ("WIN_TP3", "LOSS") and isinstance(t.get("result_delta"), (int, float))]
    gross_up = sum(max(0.0, float(t["result_delta"])) for t in completed)
    gross_down = sum(min(0.0, float(t["result_delta"])) for t in completed)
    net_delta = gross_up + gross_down
    return (
        f"📊 <b>{title}</b>\n"
        f"إجمالي الصفقات المغلقة: {total}\n"
        f"🟢 مكتملة TP3: {wins}\n"
        f"🔴 خسارة قبل الأهداف: {losses}\n"
        f"🟠 هدف ثم استوب (مختلطة): {mixed}\n"
        f"⚠️ غير محسومة داخل شمعة: {ambiguous}\n"
        f"⏳ صفقات مفتوحة حالياً: {open_count}\n"
        f"نسبة النجاح بين صفقات TP3 والخسارة المباشرة: {rate:.1f}%\n"
        f"فرق السعر للصفقات المحسومة فقط (دولار/أونصة): +{gross_up:.2f} / {gross_down:.2f} / الصافي {net_delta:+.2f}\n"
        "ملاحظة: هذا فرق سعري بالدولار لكل أونصة على GC=F وليس نقاط وسيطك؛ لا يُحسب صافي الصفقة المختلطة دون تحديد نسب الإغلاق الجزئي."
    )

def main():
    state = load_state()
    now = utc_now()
    try:
        data = fetch_json(SIGNAL_URL, "ملف الإشارة")
        if not isinstance(data, dict):
            raise ValueError("محتوى signal.json ليس كائن JSON")
        signal, updated, candle = validate_signal(data)
        updated_age = (now - updated).total_seconds()
        candle_age = (now - candle).total_seconds()

        quote_error = None
        try:
            bars = fetch_quote_bars()
        except Exception as quote_exc:
            bars = []
            quote_error = str(quote_exc)
        latest = bars[-1] if bars else None
        quote_age = (now.timestamp() - latest["ts"]) if latest else None
        quote_stale = latest is None or quote_age > MAX_QUOTE_AGE_SECONDS
        events = []
        if quote_stale:
            detail = f" عمر آخر شمعة {age_text(quote_age)}." if quote_age is not None else f" السبب: {html.escape(quote_error or 'لا توجد بيانات أسعار')}."
            events.append("⚠️ <b>أسعار XAUUSD غير متاحة أو قديمة.</b>" + detail + " لم يتم حسم أي صفقة دون سعر حديث.")
        current_key = signal_key(data, signal)
        active = state.setdefault("active_trades", [])
        closed = state.setdefault("closed_trades", [])

        # Register each distinct actionable setup once. WAIT is reported but is not a trade.
        if signal in ("BUY", "SELL") and current_key != state.get("last_signal_key"):
            existing = any(t.get("signal_key") == current_key for t in active + closed)
            if not existing:
                trade = {
                    "signal_key": current_key, "side": signal,
                    "entry": float(data["entry"]), "stop_loss": float(data["stop_loss"]),
                    "targets": [float(data[k]) for k in LEVELS],
                    "signal_updated_utc": updated.isoformat(),
                    "candle_time": data["candle_time"],
                    "created_at": now.isoformat(), "status": "OPEN",
                    "highest_target": 0, "target_hit_times": {},
                    "last_checked_bar": latest["ts"] if latest and not quote_stale else int(now.timestamp())
                }
                active.append(trade)
                events.append(
                    "📣 <b>بدأت مراقبة صفقة جديدة</b>\n"
                    f"الاتجاه: {direction_ar(signal)}\n"
                    f"الدخول: {num(trade['entry'])} | SL: {num(trade['stop_loss'])}\n"
                    f"TP1: {num(trade['targets'][0])} | TP2: {num(trade['targets'][1])} | TP3: {num(trade['targets'][2])}\n"
                    "ستُراقب مستويات TP/SL على شموع الذهب GC=F ذات الدقيقة الواحدة."
                )
            state["last_signal_key"] = current_key
        elif signal == "WAIT":
            state["last_signal_key"] = current_key

        # Process all unseen one-minute bars in chronological order for every open trade.
        last_bar = int(state.get("last_bar_ts", 0))
        new_bars = [b for b in bars if b["ts"] > last_bar] if not quote_stale else []
        for bar in new_bars:
            for trade in list(active):
                process_bar_for_trade(trade, bar, events)
            state["last_bar_ts"] = bar["ts"]

        still_open = []
        for trade in active:
            if trade.get("status") == "OPEN":
                still_open.append(trade)
            else:
                closed.append(trade)
        state["active_trades"] = still_open
        # Retain up to one year of closed history.
        cutoff = now - timedelta(days=370)
        state["closed_trades"] = [t for t in closed if not t.get("closed_at") or parse_time(t["closed_at"]) >= cutoff]

        # Signal message only when the setup changes, not on every timestamp refresh.
        if signal in ("BUY", "SELL") and current_key != state.get("last_announced_key"):
            events.insert(0, signal_message(data, signal, updated, candle, now, latest, updated_age, candle_age))
            state["last_announced_key"] = current_key
        if signal == "WAIT" and current_key != state.get("last_announced_key"):
            events.insert(0, signal_message(data, signal, updated, candle, now, latest, updated_age, candle_age))
            state["last_announced_key"] = current_key

        if quote_stale:
            warning_key = "quote_stale"
        elif updated_age > MAX_SIGNAL_AGE_SECONDS:
            warning_key = "signal_stale"
        elif candle_age > MAX_CANDLE_AGE_SECONDS:
            warning_key = "candle_stale"
        else:
            warning_key = None
        if warning_key and state.get("last_quote_warning") != warning_key:
            warning_text = {
                "quote_stale": "أسعار XAUUSD قديمة أو غير متاحة؛ لم يتم حسم أي صفقة.",
                "signal_stale": "updated_utc قديم.",
                "candle_stale": "candle_time قديم؛ تحديث الملف لا يثبت حداثة الشمعة."
            }[warning_key]
            events.append("⚠️ <b>تنبيه حداثة البيانات:</b> " + warning_text)
        state["last_quote_warning"] = warning_key

        yday = now.astimezone(YEMEN).date()
        day_key = yday.isoformat()
        trades_all = state["closed_trades"] + state["active_trades"]
        if state.get("last_daily_yemen_day") != day_key:
            start = datetime.combine(yday, datetime.min.time(), YEMEN).astimezone(timezone.utc)
            end = start + timedelta(days=1)
            events.append(summarize(trades_all, start, end, "جرد نتائج اليوم"))
            state["last_daily_yemen_day"] = day_key
        week_key = f"{yday.isocalendar().year}-W{yday.isocalendar().week:02d}"
        if yday.weekday() == 0 and state.get("last_weekly_key") != week_key:
            start_day = yday - timedelta(days=7)
            start = datetime.combine(start_day, datetime.min.time(), YEMEN).astimezone(timezone.utc)
            end = datetime.combine(yday, datetime.min.time(), YEMEN).astimezone(timezone.utc)
            events.append(summarize(trades_all, start, end, "الجرد الأسبوعي السابق"))
            state["last_weekly_key"] = week_key
        month_key = f"{yday.year}-{yday.month:02d}"
        if yday.day == 1 and state.get("last_monthly_key") != month_key:
            if yday.month == 1:
                prev_start_day = yday.replace(year=yday.year - 1, month=12, day=1)
            else:
                prev_start_day = yday.replace(month=yday.month - 1, day=1)
            start = datetime.combine(prev_start_day, datetime.min.time(), YEMEN).astimezone(timezone.utc)
            end = datetime.combine(yday, datetime.min.time(), YEMEN).astimezone(timezone.utc)
            events.append(summarize(trades_all, start, end, "الجرد الشهري السابق"))
            state["last_monthly_key"] = month_key

        if events:
            disclaimer = "\n\n<i>المراقبة تعتمد على سعر XAUUSD الاسترشادي من Yahoo Finance، وقد يختلف عن سعر وسيطك ولا تمثل سجلاً لتنفيذ الوسيط. نتائج المراقبة آلية وغير مضمونة.</i>"
            for event in events:
                send_telegram("👑 <b>أسطورة المجال</b>\n\n" + event + disclaimer)
        state["last_error"] = None
        save_state(state)
        quote_label = num(latest["close"]) if latest else "unavailable"
        quote_age_label = f"{int(quote_age)}s" if quote_age is not None else "unavailable"
        print(f"OK quote={quote_label} quote_age={quote_age_label} bars={len(new_bars)} active={len(state['active_trades'])} closed={len(state['closed_trades'])} messages={len(events)}")
    except Exception as exc:
        fingerprint = hashlib.sha256(str(exc).encode()).hexdigest()
        if state.get("last_error") != fingerprint:
            try:
                send_telegram(
                    "🚨 <b>تعذر تحديث مراقبة الذهب وجرد الصفقات</b>\n\n"
                    f"السبب: <code>{html.escape(str(exc)[:600])}</code>\n"
                    "لم يتم اعتبار تعذر التحقق ربحاً أو خسارة، ولم تُغلق الصفقات المفتوحة."
                )
                state["last_error"] = fingerprint
                save_state(state)
            except Exception as telegram_error:
                print(f"Telegram alert failed: {telegram_error}", file=sys.stderr)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()
