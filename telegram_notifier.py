#!/usr/bin/env python3
import hashlib
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone, timedelta

SIGNAL_URL = "https://raw.githubusercontent.com/azzam774169177-jpg/alhaidani-gold-analyzer/main/signal.json"
STATE_PATH = ".telegram-state.json"
REQUIRED = ["signal", "price", "entry", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3", "data_source", "candle_time", "updated_utc"]
YEMEN = timezone(timedelta(hours=3))

def parse_time(value):
    if not isinstance(value, str) or not value.strip():
        raise ValueError("وقت مفقود أو غير صالح")
    dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        raise ValueError("الوقت يجب أن يتضمن المنطقة الزمنية")
    return dt.astimezone(timezone.utc)

def age_text(seconds):
    seconds = max(0, int(seconds))
    minutes = seconds // 60
    if minutes < 60:
        return f"{minutes} دقيقة"
    hours = minutes // 60
    if hours < 48:
        return f"{hours} ساعة و{minutes % 60} دقيقة"
    return f"{hours // 24} يوم و{hours % 24} ساعة"

def send_telegram(text):
    token = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
    if not token or not chat_id:
        raise RuntimeError("يجب ضبط TELEGRAM_BOT_TOKEN و TELEGRAM_CHAT_ID في GitHub Secrets")
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    body = urllib.parse.urlencode({"chat_id": chat_id, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"}).encode()
    req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=25) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError("Telegram API رفض إرسال الرسالة")
    return True

def load_state():
    try:
        with open(STATE_PATH, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {}

def save_state(state):
    with open(STATE_PATH, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)
        f.write("\n")

def main():
    now = datetime.now(timezone.utc)
    state = load_state()
    try:
        req = urllib.request.Request(SIGNAL_URL, headers={"User-Agent": "Alhaidani-Gold-Telegram-Notifier/1.0"})
        with urllib.request.urlopen(req, timeout=20) as response:
            if response.status != 200:
                raise RuntimeError(f"HTTP {response.status}")
            raw = response.read()
        data = json.loads(raw.decode("utf-8"))
        missing = [key for key in REQUIRED if key not in data or data[key] is None or data[key] == ""]
        if missing:
            raise ValueError("حقول ناقصة: " + ", ".join(missing))
        signal = str(data["signal"]).upper()
        if signal not in ("BUY", "SELL", "WAIT"):
            raise ValueError("قيمة signal يجب أن تكون BUY أو SELL أو WAIT")
        for key in ["price", "entry", "stop_loss", "take_profit_1", "take_profit_2", "take_profit_3"]:
            if not isinstance(data[key], (int, float)) or isinstance(data[key], bool):
                raise ValueError(f"الحقل {key} ليس رقماً")
        updated = parse_time(data["updated_utc"])
        candle = parse_time(data["candle_time"])
        updated_age = (now - updated).total_seconds()
        candle_age = (now - candle).total_seconds()
        updated_stale = updated_age > 15 * 60
        candle_stale = candle_age > 30 * 60
        digest = hashlib.sha256(raw).hexdigest()
        changed = digest != state.get("last_digest")
        yemen_day = now.astimezone(YEMEN).date().isoformat()
        daily_due = state.get("last_daily_yemen_day") != yemen_day

        direction = {"BUY": "🟢 شراء BUY", "SELL": "🔴 بيع SELL", "WAIT": "🟡 انتظار WAIT"}[signal]
        source = str(data["data_source"])
        msg = (
            "👑 <b>أسطورة المجال | تحليل الذهب</b>\n\n"
            f"<b>الاتجاه:</b> {direction}\n"
            f"💰 السعر: <code>{data['price']}</code>\n"
            f"🎯 الدخول: <code>{data['entry']}</code>\n"
            f"🛑 وقف الخسارة: <code>{data['stop_loss']}</code>\n"
            f"TP1: <code>{data['take_profit_1']}</code>\n"
            f"TP2: <code>{data['take_profit_2']}</code>\n"
            f"TP3: <code>{data['take_profit_3']}</code>\n\n"
            f"🕒 تحديث الملف: {updated.isoformat()} UTC (العمر: {age_text(updated_age)})\n"
            f"🕯 وقت الشمعة: {candle.isoformat()} UTC (العمر: {age_text(candle_age)})\n"
            f"📡 المصدر: <code>{source}</code>\n"
            "⚠️ المصدر GC=F للعقود الآجلة وليس السعر الفوري XAUUSD."
        )
        warnings = []
        if updated_stale:
            warnings.append("⚠️ <b>تنبيه: updated_utc قديم؛ لم يتحدث الملف خلال 15 دقيقة.</b>")
        if candle_stale:
            warnings.append("⚠️ <b>تنبيه: candle_time قديم؛ عمر الشمعة تجاوز 30 دقيقة. تحديث الملف لا يثبت حداثة الشمعة.</b>")
        if warnings:
            msg += "\n\n" + "\n".join(warnings)

        stale_key = updated_stale or candle_stale
        stale_changed = state.get("stale_status") != stale_key
        should_send = changed or daily_due or stale_changed
        if should_send:
            header = "📢 <b>إشارة جديدة أو متغيرة</b>\n\n" if changed else ("📅 <b>التقرير اليومي</b>\n\n" if daily_due else "🔔 <b>تغير حالة حداثة البيانات</b>\n\n")
            send_telegram(header + msg + "\n\n<i>معلومات تحليلية آلية وليست توصية مضمونة أو توجيهاً لتنفيذ صفقة.</i>")
            state["last_digest"] = digest
            if daily_due:
                state["last_daily_yemen_day"] = yemen_day
            state["stale_status"] = stale_key
            save_state(state)
        print(f"OK changed={changed} daily={daily_due} updated_stale={updated_stale} candle_stale={candle_stale} sent={should_send}")
    except Exception as exc:
        err = f"🚨 <b>تعذر التحقق من إشارة الذهب</b>\n\nالسبب: <code>{str(exc)[:700]}</code>\n\nلم يتم اعتبار ذلك عدم تغير في الإشارة.\n⚠️ أي إشارة سابقة لا تُعد صالحة تلقائياً."
        fingerprint = hashlib.sha256(str(exc).encode()).hexdigest()
        if state.get("last_error") != fingerprint:
            send_telegram(err)
            state["last_error"] = fingerprint
            save_state(state)
        print(f"ERROR: {exc}", file=sys.stderr)
        raise

if __name__ == "__main__":
    main()
