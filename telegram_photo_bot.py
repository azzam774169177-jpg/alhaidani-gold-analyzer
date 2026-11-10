#!/usr/bin/env python3
"""Long-polling Telegram group photo bot. Requires a continuously running worker."""
from __future__ import annotations
import json, os, time, urllib.parse, urllib.request
from pathlib import Path
from photo_chart_analyzer import analyze_chart_image

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "").strip()
API = f"https://api.telegram.org/bot{TOKEN}/"

def api(method, params=None, timeout=45):
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(API + method, data=data if params is not None else None)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        payload = json.loads(r.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "Telegram API error"))
    return payload["result"]

def send(chat_id, reply_id, text):
    api("sendMessage", {
        "chat_id": str(chat_id),
        "reply_to_message_id": str(reply_id),
        "text": text,
        "disable_web_page_preview": "true"
    })

def get_photo_bytes(file_id):
    info = api("getFile", {"file_id": file_id})
    file_path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    with urllib.request.urlopen(url, timeout=35) as r:
        return r.read()

def format_result(result):
    if result.get("status") == "WAIT":
        return "👑 أسطورة المجال | فحص الشارت\n🟡 انتظار\n" + result.get("reason", "الصورة غير كافية للتحليل.")
    direction = "🟢" if result["status"] == "UP" else "🔴"
    return (
        "👑 أسطورة المجال | فحص الشارت\n"
        f"{direction} {result['bias']}\n"
        f"🟢 بكسلات خضراء: {result['green_share']}%\n"
        f"🔴 بكسلات حمراء: {result['red_share']}%\n"
        "⚠️ قراءة بصرية تجريبية فقط؛ لا تتضمن سعراً أو دخولاً أو استوباً، ولا تعتبر توصية تداول."
    )

def main():
    if not TOKEN:
        raise SystemExit("ضع TELEGRAM_BOT_TOKEN في متغيرات البيئة؛ لا تضعه داخل الكود.")
    # Avoid discarding pending updates on startup.
    offset = None
    print("Photo analyzer polling started.")
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": json.dumps(["message"])}
            if offset is not None:
                params["offset"] = offset
            updates = api("getUpdates", params, timeout=40)
            for update in updates:
                offset = int(update["update_id"]) + 1
                msg = update.get("message") or {}
                chat = msg.get("chat") or {}
                if chat.get("type") not in ("group", "supergroup"):
                    continue
                if ALLOWED_CHAT and str(chat.get("id")) != ALLOWED_CHAT:
                    continue
                photos = msg.get("photo") or []
                if not photos:
                    continue
                try:
                    # Telegram orders photo sizes from smallest to largest.
                    image_bytes = get_photo_bytes(photos[-1]["file_id"])
                    result = analyze_chart_image(image_bytes)
                    send(chat["id"], msg["message_id"], format_result(result))
                except Exception as exc:
                    print(f"Photo processing error: {type(exc).__name__}: {exc}")
                    send(chat["id"], msg["message_id"], "🟡 تعذر فحص الصورة حالياً. أعد إرسال لقطة واضحة للشارت.")
        except Exception as exc:
            print(f"Polling error: {type(exc).__name__}: {exc}")
            time.sleep(5)

if __name__ == "__main__":
    main()
