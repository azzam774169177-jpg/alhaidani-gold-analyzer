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
    # Prefer a comma-separated list for multiple destinations; retain the
    # original single-chat secret as a backward-compatible fallback.
    raw_chat_ids = os.environ.get("TELEGRAM_CHAT_IDS", "").strip()
    if raw_chat_ids:
        chat_ids = [item.strip() for item in raw_chat_ids.split(",") if item.strip()]
    else:
        single_chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
        chat_ids = [single_chat_id] if single_chat_id else []
    if not token or not chat_ids:
        raise RuntimeError("أضف TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_IDS (أو TELEGRAM_CHAT_ID) في GitHub Secrets")

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chat_id in chat_ids:
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
            membership = "تعذر فحص عضوية البوت في الوجهة " + chat_id
            try:
                check = urllib.request.urlopen(
                    f"https://api.telegram.org/bot{token}/getMe", timeout=15
                )
                me = json.loads(check.read().decode("utf-8"))
                if me.get("ok"):
                    bot_identity = "البوت المرتبط بالرمز: @" + me["result"].get("username", "بدون اسم مستخدم")
                    bot_id = me.get("result", {}).get("id")
                    member_url = "https://api.telegram.org/bot" + token + "/getChatMember?" + urllib.parse.urlencode({
                        "chat_id": chat_id, "user_id": bot_id
                    })
                    member_response = urllib.request.urlopen(member_url, timeout=15)
                    member = json.loads(member_response.read().decode("utf-8"))
                    if member.get("ok"):
                        info = member.get("result", {})
                        membership = "حالة البوت في الوجهة " + chat_id + ": " + str(info.get("status"))
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
            raise RuntimeError(f"Telegram رفض الإرسال إلى {chat_id}: {result.get('description', 'سبب غير معروف')}")
    return True

def load_admin_controls():
    defaults = {
        "signals_paused": False, "max_concurrent_trades": 3,
        "max_daily_trades": 20, "daily_net_profit_target_points": 100.0,
        "min_quality_score": 65, "trade_target_points": 10.0,
        "trade_stop_points": 10.0, "daily_net_loss_limit_points": 50.0
    }
    try:
        with open("admin_controls.json", "r", encoding="utf-8") as f:
            supplied = json.load(f)
        if isinstance(supplied, dict):
            defaults.update(supplied)
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    defaults["max_concurrent_trades"] = max(1, min(3, int(defaults["max_concurrent_trades"])))
    defaults["min_quality_score"] = max(0, min(100, int(defaults["min_quality_score"])))
    defaults["trade_target_points"] = max(0.1, min(100.0, float(defaults["trade_target_points"])))
    defaults["trade_stop_points"] = max(0.1, min(100.0, float(defaults["trade_stop_points"])))
    defaults["daily_net_loss_limit_points"] = max(1.0, min(10000.0, float(defaults["daily_net_loss_limit_points"])))
    defaults["max_daily_trades"] = max(1, min(50, int(defaults["max_daily_trades"])))
    defaults["daily_net_profit_target_points"] = max(1.0, min(10000.0, float(defaults["daily_net_profit_target_points"])))
    return defaults


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
        "closed_trades": [], "next_trade_number": 1, "last_daily_yemen_day": None,
        "last_weekly_key": None, "last_monthly_key": None,
        "last_error": None, "last_quote_warning": None
    }

def daily_net_points(trades, day_key):
    """Net closed P/L in gold points; 1.00 price movement equals 1 point (10 pips)."""
    total = 0.0
    for trade in trades:
        closed_at = trade.get("closed_at")
        result = trade.get("result_delta")
        if not closed_at or not isinstance(result, (int, float)):
            continue
        if trade.get("status") not in ("WIN_TP1", "WIN_TP3", "LOSS", "MIXED_AFTER_TARGET"):
            continue
        if parse_time(closed_at).astimezone(YEMEN).date().isoformat() == day_key:
            total += float(result)
    return round(total, 2)


def daily_trade_count(trades, day_key):
    """Count all trade setups registered during the Yemen calendar day."""
    count = 0
    for trade in trades:
        created_at = trade.get("created_at") or trade.get("signal_updated_utc")
        if not created_at:
            continue
        try:
            if parse_time(created_at).astimezone(YEMEN).date().isoformat() == day_key:
                count += 1
        except (TypeError, ValueError):
            continue
    return count


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

def fetch_economic_calendar():
    """Fetch Forex Factory's public weekly calendar (timestamps are UTC)."""
    url = "https://nfs.faireconomy.media/ff_calendar_thisweek.json"
    payload = fetch_json(url, "التقويم الاقتصادي Forex Factory")
    if not isinstance(payload, list):
        raise RuntimeError("صيغة التقويم الاقتصادي غير متوقعة")
    return payload



def announce_daily_news_summary(state, now):
    """Send one complete USD high/medium-impact calendar digest per Yemen day."""
    day_key = now.astimezone(YEMEN).date().isoformat()
    if state.get("daily_news_summary_date") == day_key:
        return
    try:
        calendar = fetch_economic_calendar()
    except Exception as exc:
        print(f"DAILY_NEWS_CALENDAR_WARNING: {exc}")
        return

    events = []
    for item in calendar:
        try:
            if str(item.get("country", "")).upper() != "USD":
                continue
            impact = str(item.get("impact", "")).strip().lower()
            if impact not in ("high", "medium"):
                continue
            title = str(item.get("title", "")).strip()
            raw_date = item.get("date")
            if not title or not raw_date:
                continue
            event_time = parse_time(raw_date)
            local = event_time.astimezone(YEMEN)
            if local.date().isoformat() != day_key:
                continue
            events.append((event_time, impact, title, item))
        except Exception as exc:
            print(f"DAILY_NEWS_EVENT_WARNING: {exc}")

    if not events:
        print("DAILY_NEWS_SUMMARY: no USD high/medium events found for today; will retry next cycle.")
        return

    events.sort(key=lambda row: row[0])
    lines = [
        "👑 <b>أسطورة المجال | الأجندة الاقتصادية الكاملة لليوم</b>",
        f"📅 {day_key} | بتوقيت اليمن",
        "━━━━━━━━━━━━━━━━━━"
    ]
    for event_time, impact, title, item in events:
        local = event_time.astimezone(YEMEN)
        status = "انتهى موعده" if event_time < now else "قادم"
        impact_ar = "🔴 قوي جداً" if impact == "high" else "🟠 متوسط"
        impact_pct = 90 if impact == "high" else 65
        forecast = str(item.get("forecast") or "غير متوفر")
        previous = str(item.get("previous") or "غير متوفر")
        actual = str(item.get("actual") or "لم يصدر")
        lines.extend([
            f"\n⏰ <b>{local.strftime('%H:%M')} — {html.escape(title)}</b>",
            f"قوة التأثير التقديرية: {impact_pct}% ({impact_ar}) | الحالة: {status}",
            f"الفعلي: {html.escape(actual)} | التوقع: {html.escape(forecast)} | السابق: {html.escape(previous)}"
        ])

    lines.extend([
        "\n━━━━━━━━━━━━━━━━━━",
        "🥇 <b>قراءة الذهب XAUUSD:</b>",
        "• بيانات أمريكية أقوى من التوقعات غالباً تدعم الدولار والعوائد وتضغط على الذهب.",
        "• بيانات أضعف من التوقعات غالباً تضعف الدولار وتدعم الذهب.",
        "• تصريحات الفيدرالي تعتمد على نبرة التشديد أو التيسير؛ لا يُفترض اتجاه مسبق.",
        "📌 مقياس القوة تقديري حسب تصنيف التقويم: قوي 90%، متوسط 65%؛ وليس احتمال ربح أو توقعاً لاتجاه الذهب.",
        "⚠️ لا يمكن تحديد اتجاه الخبر قبل صدور القراءة ومقارنتها بالتوقعات. تجنب الدخول العشوائي وقت الخبر.",
        "المصدر: التقويم الاقتصادي Forex Factory؛ الأوقات محولة إلى توقيت اليمن."
    ])
    send_telegram("\n".join(lines))
    state["daily_news_summary_date"] = day_key
    save_state(state)
    print(f"DAILY_NEWS_SUMMARY_SENT: {day_key}, events={len(events)}")

def announce_upcoming_news(state, now):
    """Warn five minutes before high-impact USD news and return the active no-entry window."""
    try:
        calendar = fetch_economic_calendar()
    except Exception as exc:
        print(f"NEWS_CALENDAR_WARNING: {exc}")
        # Fail safe: without a current calendar, do not claim a news blackout.
        return False

    warned = state.setdefault("announced_economic_events_5m", [])
    warned_set = set(warned)
    blackout_active = False
    for item in calendar:
        try:
            currency = str(item.get("country", "")).upper()
            impact = str(item.get("impact", "")).strip().lower()
            title = str(item.get("title", "")).strip()
            raw_date = item.get("date")
            if currency != "USD" or impact != "high" or not title or not raw_date:
                continue
            event_time = parse_time(raw_date)
            minutes_until = (event_time - now).total_seconds() / 60

            # No new signals from 15 minutes before until 15 minutes after release.
            if -15 <= minutes_until <= 15:
                blackout_active = True

            # The workflow runs every five minutes; this window tolerates scheduler jitter.
            event_key = hashlib.sha256(
                f"{raw_date}|{currency}|{title}".encode("utf-8")
            ).hexdigest()
            if 3 <= minutes_until <= 7 and event_key not in warned_set:
                local_time = event_time.astimezone(YEMEN).strftime("%H:%M")
                local_date = event_time.astimezone(YEMEN).strftime("%Y-%m-%d")
                forecast = str(item.get("forecast") or "غير متوفر")
                previous = str(item.get("previous") or "غير متوفر")
                message = (
                    "🚨 <b>أسطورة المجال | تحذير: خبر أمريكي بعد 5 دقائق</b>\n\n"
                    f"📰 الخبر: <b>{html.escape(title)}</b>\n"
                    f"💵 العملة: <b>{currency}</b> | 🔴 التأثير: <b>عالٍ</b>\n"
                    f"⏰ الموعد: <b>{local_time} بتوقيت اليمن</b>\n"
                    f"📅 التاريخ: <b>{local_date}</b>\n"
                    f"📊 التوقع: {html.escape(forecast)} | السابق: {html.escape(previous)}\n\n"
                    "⛔ يوقف البوت إصدار صفقات جديدة قبل الخبر بـ15 دقيقة وحتى 15 دقيقة بعد صدوره.\n"
                    "⚠️ قد يرتفع التذبذب والسيولة؛ انتظر هدوء السوق وتأكيد الحركة.\n"
                    "المصدر: Forex Factory"
                )
                send_telegram(message)
                warned.append(event_key)
                warned_set.add(event_key)
                state["announced_economic_events_5m"] = warned[-500:]
                save_state(state)
                print(f"ECONOMIC_NEWS_5M_WARNING_SENT: {title} at {raw_date}")
        except Exception as exc:
            print(f"NEWS_EVENT_WARNING: {exc}")

    state["announced_economic_events_5m"] = warned[-500:]
    if blackout_active:
        print("NEWS_BLACKOUT_ACTIVE: high-impact USD event within +/-15 minutes; new signals blocked.")
    return blackout_active


def fetch_quote_bars():
    payload = fetch_json(QUOTE_URL, "مصدر الذهب GC=F (عقود COMEX الاسترشادية من Yahoo Finance)")
    result = payload.get("chart", {}).get("result")
    if not result:
        error = payload.get("chart", {}).get("error")
        raise RuntimeError(f"تعذر الحصول على أسعار عقود الذهب COMEX الاسترشادية: {error}")
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
        raise RuntimeError("مصدر GC=F لم يُرجع شموعاً صالحة")
    return bars

def validate_signal(data):
    missing = [key for key in REQUIRED if key not in data or data[key] == ""]
    if missing:
        raise ValueError("حقول ناقصة: " + ", ".join(missing))
    signal = str(data["signal"]).upper()
    if signal not in ("BUY", "SELL", "WAIT"):
        raise ValueError("قيمة signal يجب أن تكون BUY أو SELL أو WAIT")
    if not isinstance(data["price"], (int, float)) or isinstance(data["price"], bool):
        raise ValueError("الحقل price ليس رقماً")
    updated = parse_time(data["updated_utc"])
    candle = parse_time(data["candle_time"])
    # WAIT is a valid no-trade state: levels may be null.
    if signal in ("BUY", "SELL"):
        for key in ["entry", "stop_loss"] + LEVELS:
            if not isinstance(data[key], (int, float)) or isinstance(data[key], bool):
                raise ValueError(f"الحقل {key} ليس رقماً لإشارة تداول فعلية")
        if signal == "BUY":
            valid = data["stop_loss"] < data["entry"] < data["take_profit_1"] <= data["take_profit_2"] <= data["take_profit_3"]
        else:
            valid = data["stop_loss"] > data["entry"] > data["take_profit_1"] >= data["take_profit_2"] >= data["take_profit_3"]
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
        f"💰 السعر عند التحليل: <code>{num(data['price'])}</code>\n"
    )
    if signal == "WAIT":
        msg += (
            f"📝 السبب: {html.escape(str(data.get('reason', 'لا توجد فرصة واضحة حالياً')))}\n"
            "⛔ لا توجد صفقة؛ الدخول ووقف الخسارة والأهداف غير محددة.\n"
        )
    else:
        msg += (
            f"🎯 الدخول: <code>{num(data['entry'])}</code>\n"
            f"🛑 وقف الخسارة: <code>{num(data['stop_loss'])}</code>\n"
            f"TP1: <code>{num(data['take_profit_1'])}</code>\n"
            f"TP2: <code>{num(data['take_profit_2'])}</code>\n"
            f"TP3: <code>{num(data['take_profit_3'])}</code>\n"
        )
    msg += (
        f"\n📈 آخر سعر مراقَب GC=F: <code>{num(quote['close']) if quote else 'غير متاح'}</code>\n"
        f"🕒 تحديث الملف: {fmt_time(updated)} (العمر {age_text(updated_age)})\n"
        f"🕯 وقت الشمعة: {fmt_time(candle)} (العمر {age_text(candle_age)})\n"
        f"📡 المصدر: <code>{html.escape(str(data['data_source']))}</code>\n"
        "⚠️ المصدر GC=F عقود ذهب COMEX استرشادية من Yahoo Finance؛ قد يختلف عن XAUUSD لدى Weltrade."
    )
    if updated_age > MAX_SIGNAL_AGE_SECONDS:
        msg += "\n⚠️ <b>تحذير: updated_utc قديم.</b>"
    if candle_age > MAX_CANDLE_AGE_SECONDS:
        msg += "\n⚠️ <b>تحذير: candle_time قديم؛ تحديث الملف لا يثبت حداثة الشمعة.</b>"
    return msg

def historical_success_rate(state):
    rows = [t for t in state.get("closed_trades", []) if t.get("status") in ("WIN_TP1", "WIN_TP3", "LOSS")]
    wins = sum(1 for t in rows if t.get("status") in ("WIN_TP1", "WIN_TP3"))
    total = len(rows)
    if total == 0:
        return "نسبة النجاح التاريخية: غير متاحة (لا توجد صفقات محسومة)"
    rate = wins / total * 100
    return f"نسبة نجاح الصفقات التاريخية: {rate:.1f}% ({wins} من {total})"


def ready_trade_message(data, signal, state):
    side = "🟢 شراء BUY" if signal == "BUY" else "🔴 بيع SELL"
    return (
        "👑 <b>أسطورة المجال | صفقة XAUUSD جاهزة</b>\n\n"
        "🥇 الزوج: <b>XAUUSD</b>\n"
        f"📌 الاتجاه: <b>{side}</b>\n"
        f"💰 سعر الدخول: <code>{num(data['entry'])}</code>\n"
        f"🛑 وقف الخسارة: <code>{num(data['stop_loss'])}</code> (10 نقاط)\n"
        f"🎯 الهدف الوحيد TP1: <code>{num(data['take_profit_1'])}</code> (10 نقاط)\n\n"
        f"{historical_success_rate(state)}\n"
        f"🕯 الإطار: {html.escape(str(data.get('timeframe', '15m')))}\n"
        f"📝 السبب الفني: {html.escape(str(data.get('reason', 'توافق فني')))}\n"
        f"🕒 وقت التحليل: {fmt_time(parse_time(data['updated_utc']))}\n"
        "⚠️ النسبة تاريخية للصفقات المحسومة فقط وليست توقعاً أو ضماناً لنجاح الصفقة الحالية. "
        "تحقق من سعر XAUUSD لدى وسيطك قبل التنفيذ؛ قد يختلف السعر المرجعي عن سعر التنفيذ."
    )


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
    target_count = int(trade.get("target_count", 3))
    return f"{side} | دخول {num(trade['entry'])} | أفضل هدف {trade.get('highest_target', 0)}/{target_count} | الحالة: {html.escape(trade['status'])}"

def process_bar_for_trade(trade, bar, events):
    status = trade.get("status")
    if status not in ("PENDING", "OPEN", "ACTIVE") or bar["ts"] <= trade.get("last_checked_bar", 0):
        return

    # New setups wait for price to reach the entry. Legacy OPEN trades remain
    # monitored as already activated so existing state is not lost.
    if status == "PENDING":
        entry = float(trade["entry"])
        reached_entry = (
            bar["low"] <= entry if trade["side"] == "BUY"
            else bar["high"] >= entry
        )
        trade["last_checked_bar"] = bar["ts"]
        if not reached_entry:
            return
        trade["status"] = "ACTIVE"
        trade["activated_at"] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        trade_id = trade.setdefault("trade_id", trade.get("signal_key", "legacy")[:12])
        events.append(
            "🟢 تم تفعيل الصفقة ✅\n\n"
            f"🆔 رقم الصفقة: ( {html.escape(trade_id)} )"
        )
        # Do not infer TP/SL ordering from the same one-minute candle that
        # first activated the setup; begin outcome monitoring on the next bar.
        return

    next_idx = int(trade.get("highest_target", 0))
    target_count = max(1, min(3, int(trade.get("target_count", 3))))
    # If this one-minute candle touches the stop and any remaining target,
    # OHLC data cannot establish which price happened first: classify as ambiguous.
    any_target = any(target_hit(trade, bar, i) for i in range(next_idx, target_count))
    stopped = stop_hit(trade, bar)
    if stopped and any_target:
        trade["status"] = "AMBIGUOUS_SL_AND_TP_SAME_CANDLE"
        trade["closed_at"] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        trade["close_price"] = None
        trade["ambiguous"] = True
        trade["last_checked_bar"] = bar["ts"]
        trade_id = trade.setdefault("trade_id", trade.get("signal_key", "legacy")[:12])
        events.append(
            "⚠️ نتيجة الصفقة غير محسومة داخل شمعة واحدة\n\n"
            f"🆔 رقم الصفقة: ( {html.escape(trade_id)} )"
        )
        return
    if stopped:
        if trade.get("highest_target", 0) == 0:
            trade["status"] = "LOSS"
            outcome = "🛑 <b>تم ضرب وقف الخسارة</b>"
        else:
            trade["status"] = "MIXED_AFTER_TARGET"
            outcome = f"🛑 <b>تم ضرب وقف الخسارة بعد تحقيق TP{trade['highest_target']}</b>"
        trade["closed_at"] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        trade["close_price"] = float(trade["stop_loss"])
        trade["result_delta"] = favorable_distance(trade, trade["stop_loss"])
        trade["last_checked_bar"] = bar["ts"]
        stop_distance = abs(float(trade["stop_loss"]) - float(trade["entry"]))
        stop_points = stop_distance
        stop_pips = stop_points * 10
        trade_id = trade.setdefault("trade_id", trade.get("signal_key", "legacy")[:12])
        events.append(
            "🎯 تم ضرب استوب ❌\n\n"
            f"🛑 Stop Loss: {stop_pips:g} Pips ❌\n\n"
            f"🆔 رقم الصفقة: ( {html.escape(trade_id)} )"
        )
        return
    # Multiple targets can be crossed in one candle; record every reached level.
    while trade.get("highest_target", 0) < target_count:
        idx = int(trade.get("highest_target", 0))
        if not target_hit(trade, bar, idx):
            break
        idx += 1
        trade["highest_target"] = idx
        trade["target_hit_times"][str(idx)] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        target_price = trade["targets"][idx - 1]
        distance = abs(float(target_price) - float(trade["entry"]))
        if idx == 1:
            points = distance
            pips = points * 10
            trade_id = trade.setdefault("trade_id", trade.get("signal_key", "legacy")[:12])
            events.append(
                "🎯 تم هدفك بنجاح ✅\n\n"
                f"{pips:g} Pips = {points:g} Points ✅🔥\n\n"
                f"🆔 رقم الصفقة: ( {html.escape(trade_id)} )"
            )
        else:
            trade_id = trade.setdefault("trade_id", trade.get("signal_key", "legacy")[:12])
            events.append(
                f"🎯 تم تحقيق الهدف TP{idx} ✅\n\n"
                f"🆔 رقم الصفقة: ( {html.escape(trade_id)} )"
            )
    if trade.get("highest_target", 0) >= target_count:
        trade["status"] = "WIN_TP1" if target_count == 1 else "WIN_TP3"
        trade["closed_at"] = datetime.fromtimestamp(bar["ts"], timezone.utc).isoformat()
        final_target = float(trade["targets"][target_count - 1])
        trade["close_price"] = final_target
        trade["result_delta"] = favorable_distance(trade, final_target)
        trade["last_checked_bar"] = bar["ts"]
        trade_id = trade.setdefault("trade_id", trade.get("signal_key", "legacy")[:12])
        target_label = "TP1" if target_count == 1 else "TP3"
        events.append(
            "🏆 اكتملت الصفقة بنجاح ✅\n\n"
            f"🆔 رقم الصفقة: ( {html.escape(trade_id)} )"
        )
    else:
        trade["last_checked_bar"] = bar["ts"]

def summarize(trades, start, end, title):
    rows = [t for t in trades if t.get("closed_at") and start <= parse_time(t["closed_at"]) < end]
    wins = sum(1 for t in rows if t["status"] in ("WIN_TP1", "WIN_TP3"))
    losses = sum(1 for t in rows if t["status"] == "LOSS")
    mixed = sum(1 for t in rows if t["status"] == "MIXED_AFTER_TARGET")
    ambiguous = sum(1 for t in rows if t["status"] == "AMBIGUOUS_SL_AND_TP_SAME_CANDLE")
    open_count = sum(1 for t in trades if t.get("status") in ("PENDING", "OPEN", "ACTIVE"))
    total = len(rows)
    decided = wins + losses
    rate = (wins / decided * 100) if decided else 0
    completed = [t for t in rows if t.get("status") in ("WIN_TP1", "WIN_TP3", "LOSS") and isinstance(t.get("result_delta"), (int, float))]
    gross_up = sum(max(0.0, float(t["result_delta"])) for t in completed)
    gross_down = sum(min(0.0, float(t["result_delta"])) for t in completed)
    net_delta = gross_up + gross_down
    report_date = start.astimezone(YEMEN).strftime("%Y-%m-%d")
    net_label = "صافي الربح" if net_delta >= 0 else "صافي الخسارة"
    return (
        "👑 <b>آســــــــطورة «♕» آلَمِــــــــجَآلَ</b>\n\n"
        f"📊 <b>{html.escape(title)}</b>\n"
        f"📅 {report_date}\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"📈 إجمالي الصفقات المغلقة: <b>{total} صفقات</b>\n\n"
        f"🟢 الصفقات الرابحة: <b>{wins} صفقات</b>\n\n"
        f"🔴 الصفقات الخاسرة: <b>{losses} صفقات</b>\n\n"
        f"🟠 الصفقات المختلطة: <b>{mixed}</b>\n\n"
        f"⚠️ الصفقات غير المحسومة: <b>{ambiguous}</b>\n\n"
        f"⏳ الصفقات المفتوحة حالياً: <b>{open_count}</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        f"🎯 نسبة النجاح: <b>{rate:.1f}%</b>\n\n"
        f"💚 إجمالي الأرباح: <b>+{gross_up:.2f} نقطة</b>\n\n"
        f"❤️ إجمالي الخسائر: <b>{gross_down:.2f} نقطة</b>\n\n"
        f"🏆 <b>{net_label}: {net_delta:+.2f} نقطة</b>\n\n"
        "━━━━━━━━━━━━━━━━━━\n\n"
        "📌 تُحسب نقطة الذهب على أساس حركة 1.00 في السعر (10 Pips).\n"
        "تُستثنى الصفقات المختلطة وغير المحسومة من صافي النقاط ونسبة النجاح.\n\n"
        "بفضل الله، نواصل العمل بالانضباط وإدارة رأس المال.\n"
        "👑 <b>أسطورة المجال | القادم أفضل بإذن الله</b>"
    )

def main():
    # Economic news alerts continue during maintenance; only trade publishing is paused.
    state = load_state()
    controls = load_admin_controls()
    now = utc_now()
    announce_daily_news_summary(state, now)
    news_blackout_active = announce_upcoming_news(state, now)

    # Hard maintenance lock: prevent any manual or automatic run from publishing trades.
    try:
        with open("maintenance_notice.json", "r", encoding="utf-8") as maintenance_file:
            maintenance = json.load(maintenance_file)
    except FileNotFoundError:
        maintenance = {"signals_paused": False}
    if maintenance.get("signals_paused") is True or controls.get("signals_paused") is True:
        print("MAINTENANCE: signal publishing is locked; news alerts remain enabled.")
        save_state(state)
        return
    try:
        with open("signal.json", "r", encoding="utf-8") as signal_file:
            data = json.load(signal_file)
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
        quote_stale = latest is None or quote_age > MAX_QUOTE_AGE_SECONDS or quote_age < -60
        events = []
        trade_to_publish = None
        if quote_stale:
            detail = f" عمر آخر شمعة {age_text(quote_age)}." if quote_age is not None else f" السبب: {html.escape(quote_error or 'لا توجد بيانات أسعار')}."
            events.append("⚠️ <b>أسعار XAUUSD غير متاحة أو قديمة.</b>" + detail + " لم يتم حسم أي صفقة دون سعر حديث.")
        current_key = signal_key(data, signal)
        active = state.setdefault("active_trades", [])
        closed = state.setdefault("closed_trades", [])

        # Migrate legacy hash IDs to permanent sequential numbers exactly once.
        known_trades = sorted(
            active + closed,
            key=lambda item: item.get("created_at") or item.get("signal_updated_utc") or ""
        )
        next_number = max(1, int(state.get("next_trade_number", 1) or 1))
        for known_trade in known_trades:
            number = known_trade.get("trade_number")
            if not isinstance(number, int) or number < 1:
                number = next_number
                known_trade["trade_number"] = number
                next_number += 1
            known_trade["trade_id"] = str(number)
        state["next_trade_number"] = max(
            next_number,
            max((int(item.get("trade_number", 0)) for item in known_trades), default=0) + 1
        )

        # A unique timestamp in cancel_trade.json requests one manual cancellation.
        # Only PENDING setups are cancelled; already activated trades are not closed
        # because cancellation is not proof of execution/closure at the broker.
        try:
            with open("cancel_trade.json", "r", encoding="utf-8") as cancel_file:
                cancel_request = json.load(cancel_file)
        except FileNotFoundError:
            cancel_request = {}
        cancel_request_id = cancel_request.get("cancel_requested_at")
        if (
            isinstance(cancel_request_id, str)
            and cancel_request_id.strip()
            and cancel_request_id != state.get("last_cancel_request")
        ):
            cancel_reason = html.escape(str(cancel_request.get("reason") or "إلغاء يدوي من الإدارة"))
            cancelled_count = 0
            for trade in active:
                if trade.get("status") == "PENDING":
                    trade["status"] = "CANCELLED"
                    trade["cancelled_at"] = now.isoformat()
                    trade["cancel_reason"] = str(cancel_request.get("reason") or "إلغاء يدوي من الإدارة")
                    trade_id = trade.setdefault("trade_id", trade.get("signal_key", "legacy")[:12])
                    events.append(
                        "🚫 تم إلغاء الصفقة ❌\n\n"
                        f"🆔 رقم الصفقة: ( {html.escape(trade_id)} )"
                    )
                    cancelled_count += 1
            state["last_cancel_request"] = cancel_request_id
            print(f"Manual cancellation request processed; pending_cancelled={cancelled_count}")

        # Register only actionable setups backed by fresh signal, candle, and quote data.
        day_key = now.astimezone(YEMEN).date().isoformat()
        if state.get("risk_pause_day") != day_key:
            state.pop("risk_pause_day", None)
            state.pop("risk_pause_reason", None)
        # Recalculate the lock from today's NET points; old loss-count locks are retired.
        state.pop("risk_pause_day", None)
        state.pop("risk_pause_reason", None)
        current_daily_net = daily_net_points(closed, day_key)
        daily_limit = float(controls["daily_net_loss_limit_points"])
        profit_target = float(controls["daily_net_profit_target_points"])
        daily_cap = int(controls["max_daily_trades"])
        trades_today = daily_trade_count(active + closed, day_key)
        risk_locked = current_daily_net <= -daily_limit
        profit_locked = current_daily_net >= profit_target
        count_locked = trades_today >= daily_cap
        if risk_locked:
            state["risk_pause_day"] = day_key
            state["risk_pause_reason"] = f"صافي خسارة اليوم {current_daily_net:.2f} نقطة بلغ الحد -{daily_limit:.2f}"
        actionable_fresh = (
            signal in ("BUY", "SELL")
            and not risk_locked
            and not profit_locked
            and not count_locked
            and not news_blackout_active
            and isinstance(data.get("quality_score"), (int, float))
            and data.get("quality_score", 0) >= controls["min_quality_score"]
            and not quote_stale
            and -60 <= updated_age <= MAX_SIGNAL_AGE_SECONDS
            and -60 <= candle_age <= MAX_CANDLE_AGE_SECONDS
        )
        if actionable_fresh and current_key != state.get("last_signal_key"):
            existing = any(t.get("signal_key") == current_key for t in active + closed)
            same_candle_setup = any(
                t.get("side") == signal and t.get("candle_time") == data["candle_time"]
                for t in active + closed
            )
            live_trades = [
                t for t in active
                if t.get("status") in ("PENDING", "OPEN", "ACTIVE")
            ]
            # Admin may lower the cap, but it can never exceed three concurrent trades.
            max_live = controls["max_concurrent_trades"]
            if not existing and not same_candle_setup and len(live_trades) < max_live:
                trade = {
                    "signal_key": current_key,
                    "trade_number": int(state["next_trade_number"]),
                    "trade_id": str(state["next_trade_number"]), "side": signal,
                    "entry": round(float(data["entry"]), 2),
                    "stop_loss": round(float(data["entry"]) - float(controls["trade_stop_points"]) if signal == "BUY" else float(data["entry"]) + float(controls["trade_stop_points"]), 2),
                    "targets": [round(float(data["entry"]) + float(controls["trade_target_points"]) if signal == "BUY" else float(data["entry"]) - float(controls["trade_target_points"]), 2)],
                    "target_count": 1,
                    "signal_updated_utc": updated.isoformat(),
                    "candle_time": data["candle_time"],
                    "created_at": now.isoformat(), "status": "PENDING",
                    "highest_target": 0, "target_hit_times": {},
                    "last_checked_bar": latest["ts"] if latest and not quote_stale else int(now.timestamp())
                }
                trade["quality_score"] = int(data.get("quality_score", 0))
                active.append(trade)
                state["next_trade_number"] = int(state["next_trade_number"]) + 1
                trade_to_publish = data
                state["last_signal_key"] = current_key
                print(f"NEW_TRADE_REGISTERED: concurrent={len(live_trades) + 1}/{max_live}; quality={trade['quality_score']}/100")
            elif existing or same_candle_setup:
                state["last_signal_key"] = current_key
                print("DUPLICATE_SIGNAL_IGNORED: same signal or same-side setup on same candle")
            else:
                # Do not consume the signal key: retry on the next workflow run
                # in case one of the three existing trades closes in the meantime.
                print(f"TRADE_LIMIT_REACHED: concurrent={len(live_trades)}/{max_live}; new signal not published")
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
            if trade.get("status") in ("PENDING", "OPEN", "ACTIVE"):
                still_open.append(trade)
            else:
                closed.append(trade)
        state["active_trades"] = still_open
        # Enforce the capital-protection lock immediately after newly processed outcomes.
        current_daily_net = daily_net_points(state["closed_trades"], day_key)
        if current_daily_net <= -daily_limit:
            state["risk_pause_day"] = day_key
            state["risk_pause_reason"] = f"تم بلوغ حد صافي الخسارة اليومية: {current_daily_net:.2f} نقطة"
        else:
            state.pop("risk_pause_day", None)
            state.pop("risk_pause_reason", None)
        if current_daily_net <= -daily_limit or current_daily_net >= profit_target:
            if trade_to_publish is not None:
                for pending in list(state["active_trades"]):
                    if pending.get("signal_key") == current_key and pending.get("status") == "PENDING":
                        pending["status"] = "CANCELLED_DAILY_LIMIT"
                        pending["closed_at"] = now.isoformat()
                        state["active_trades"].remove(pending)
                        state["closed_trades"].append(pending)
                trade_to_publish = None
            if current_daily_net <= -daily_limit:
                events.append("🛡️ تم تفعيل حماية رأس المال: بلوغ حد الخسارة اليومية.")
            else:
                events.append("🏁 تم تحقيق الهدف اليومي +100 نقطة صافي؛ توقفت الإشارات الجديدة.")
        # Retain up to one year of closed history.
        cutoff = now - timedelta(days=370)
        state["closed_trades"] = [t for t in closed if not t.get("closed_at") or parse_time(t["closed_at"]) >= cutoff]

        # Publish only new actionable BUY/SELL setups; never broadcast WAIT updates.
        if actionable_fresh:
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

        local_now = now.astimezone(YEMEN)
        yday = local_now.date()
        day_key = yday.isoformat()
        trades_all = state["closed_trades"] + state["active_trades"]
        report_events = []
        # Daily report: send at/after 23:55 Yemen time, or on the first
        # workflow run after midnight if the 23:55-23:59 window was missed.
        report_day = yday if (local_now.hour == 23 and local_now.minute >= 55) else (yday - timedelta(days=1))
        report_day_key = report_day.isoformat()
        if state.get("last_daily_yemen_day") != report_day_key:
            start = datetime.combine(report_day, datetime.min.time(), YEMEN).astimezone(timezone.utc)
            end = start + timedelta(days=1)
            report_events.append(summarize(trades_all, start, end, "جرد نتائج اليوم"))
            state["last_daily_yemen_day"] = report_day_key

        # Weekly report: Friday at/after 23:55, or first run on Saturday.
        report_week_day = yday if (yday.weekday() == 4 and local_now.hour == 23 and local_now.minute >= 55) else (yday - timedelta(days=1))
        week_key = f"{report_week_day.isocalendar().year}-W{report_week_day.isocalendar().week:02d}"
        if report_week_day.weekday() == 4 and state.get("last_weekly_key") != week_key:
            start_day = report_week_day - timedelta(days=4)
            start = datetime.combine(start_day, datetime.min.time(), YEMEN).astimezone(timezone.utc)
            end = datetime.combine(report_week_day + timedelta(days=1), datetime.min.time(), YEMEN).astimezone(timezone.utc)
            report_events.append(summarize(trades_all, start, end, "جرد نتائج الأسبوع"))
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

        # Only send actionable trade setups. All non-trade chatter is suppressed.
        messages_sent = 0
        if trade_to_publish is not None:
            side = "شراء" if signal == "BUY" else "بيع"
            icon = "🟢" if signal == "BUY" else "🔴"
            published_trade = next((t for t in state["active_trades"] if t.get("signal_key") == current_key), None)
            if signal == "SELL":
                message = (
                    "صفقة بيع الذهب XAUUSD🥇\n"
                    f"🔴 الدخول: {num(published_trade['entry'])}\n"
                    f"🎯 هدفك: {num(published_trade['targets'][0])}\n"
                    f"🛑 استوبك: {num(published_trade['stop_loss'])}\n\n"
                    f"{historical_success_rate(state)}\n\n"
                    f"🆔 رقم الصفقة: ( {html.escape(str(published_trade['trade_number']))} )"
                )
            else:
                message = (
                    "🟢 صفقة شراء الذهب XAUUSD🥇\n"
                    f"🟢 الدخول: {num(published_trade['entry'])}\n"
                    f"🎯 هدفك: {num(published_trade['targets'][0])}\n"
                    f"🛑 استوبك: {num(published_trade['stop_loss'])}\n\n"
                    f"{historical_success_rate(state)}\n\n"
                    f"🆔 رقم الصفقة: ( {html.escape(str(published_trade['trade_number']))} )"
                )
            send_telegram(message)
            messages_sent += 1
            print(f"TRADE_PUBLISHED: {signal} XAUUSD entry={published_trade['entry']} target={published_trade['targets'][0]} stop={published_trade['stop_loss']}")

        # Send daily/weekly reports once, only after the relevant period is complete.
        for report in report_events:
            send_telegram(report)
            messages_sent += 1
            print("PERIODIC_REPORT_SENT: " + ("weekly" if "جرد نتائج الأسبوع" in report else "daily"))

        # Publish one-time trade outcome alerts. The monitor emits these events
        # only while processing previously unseen one-minute bars; state is
        # committed by the workflow after successful delivery.
        status_events = [
            event for event in events
            if (
                "تم تفعيل الصفقة" in event
                or "تم إلغاء الصفقة" in event
                or "تم هدفك بنجاح" in event
                or "Stop Loss:" in event
                or "نتيجة غير محسومة داخل شمعة واحدة" in event
                or "تم تفعيل حماية رأس المال" in event
                or "تم تحقيق الهدف اليومي +100 نقطة صافي" in event
            )
        ]
        for event in status_events:
            send_telegram(event)
            messages_sent += 1

        if signal in ("BUY", "SELL") and trade_to_publish is None:
            blockers = []
            if risk_locked: blockers.append("daily_net_loss_limit")
            if profit_locked: blockers.append("daily_net_profit_target_reached")
            if count_locked: blockers.append("daily_trade_limit_reached")
            if news_blackout_active: blockers.append("high_impact_usd_news_blackout")
            if quote_stale: blockers.append("quote_stale")
            if not ( -60 <= updated_age <= MAX_SIGNAL_AGE_SECONDS): blockers.append("signal_stale")
            if not (-60 <= candle_age <= MAX_CANDLE_AGE_SECONDS): blockers.append("candle_stale")
            if not isinstance(data.get("quality_score"), (int, float)) or data.get("quality_score", 0) < controls["min_quality_score"]: blockers.append("quality_below_minimum")
            if not blockers: blockers.append("duplicate_or_concurrent_trade_limit")
            print("TRADE_NOT_PUBLISHED: " + ",".join(blockers))

        state["last_error"] = None
        save_state(state)
        quote_label = num(latest["close"]) if latest else "unavailable"
        quote_age_label = f"{int(quote_age)}s" if quote_age is not None else "unavailable"
        print(f"OK quote={quote_label} quote_age={quote_age_label} bars={len(new_bars)} active={len(state['active_trades'])} closed={len(state['closed_trades'])} messages_sent={messages_sent} status_events={len(status_events)}")
    except Exception as exc:
        # Errors stay in GitHub Actions logs; never send non-trade messages.
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()
