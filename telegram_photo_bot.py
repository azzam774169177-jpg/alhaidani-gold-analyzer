#!/usr/bin/env python3
"""Always-on Telegram photo-analysis worker using long polling and Gemini vision."""
from __future__ import annotations

import base64
import json
import os
import time
import urllib.parse
import urllib.request
import urllib.error

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "-1003960644699").strip()
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "").strip()
GEMINI_MODEL = os.environ.get("GEMINI_MODEL", "gemini-2.5-flash-lite").strip()
TG_API = f"https://api.telegram.org/bot{TOKEN}/"


def post_form(url: str, params: dict, timeout: int = 45):
    data = urllib.parse.urlencode(params).encode()
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/x-www-form-urlencoded"})
    with urllib.request.urlopen(req, timeout=timeout) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not payload.get("ok"):
        raise RuntimeError(payload.get("description", "API request failed"))
    return payload["result"]


def telegram(method: str, params: dict | None = None, timeout: int = 45):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    return post_form(TG_API + method, params or {}, timeout)


def send(chat_id: int, reply_id: int, message: str):
    telegram("sendMessage", {
        "chat_id": str(chat_id),
        "reply_to_message_id": str(reply_id),
        "text": message[:4000],
        "disable_web_page_preview": "true",
    })


def download_photo(file_id: str) -> tuple[bytes, str]:
    info = telegram("getFile", {"file_id": file_id})
    path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{path}"
    with urllib.request.urlopen(url, timeout=45) as response:
        raw = response.read()
    if len(raw) > 15 * 1024 * 1024:
        raise ValueError("Image exceeds 15 MB")
    if raw.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif raw.startswith(b"RIFF") and raw[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return raw, mime


def analyze_image(raw: bytes, mime: str, caption: str = "") -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt = (
        "أنت مساعد لتحليل صور شارت الذهب XAUUSD. حلّل الصورة المرفقة فقط، ولا تدّعِ "
        "أن لديك سعراً لحظياً أو بيانات MT5 مباشرة. تعليق العضو: "
        + (caption[:800] if caption else "لا يوجد")
        + "\nتحقق أن الصورة شارت تداول وأن الرمز XAUUSD ظاهر أو أن العضو ذكره. "
        "اقرأ الأسعار فقط إذا كانت واضحة تماماً. لا تخترع مستويات أو مؤشرات أو أسعاراً. "
        "إذا كانت الصورة غير واضحة أو الرمز غير مؤكد أو لا توجد فرصة مكتملة، أجب انتظاراً "
        "واشرح السبب بجملة قصيرة. لا تعطِ BUY أو SELL إلا إذا كان اتجاه الدخول ووقف الخسارة "
        "واضحين ويمكن تبريرهما من الصورة. لا تستخدم يقيناً مطلقاً ولا تعد بالربح.\n"
        "إذا وجدت فرصة واضحة، اكتب بالعربية بهذا التنسيق المختصر:\n"
        "👑 أسطورة المجال | تحليل صورة الشارت\n"
        "🟢 BUY أو 🔴 SELL — XAUUSD\n"
        "منطقة الدخول: ...\nوقف الخسارة: ...\nالهدف الأول: ...\nالهدف الثاني: ...\n"
        "الهدف الثالث: ...\nسبب الإشارة: ...\n"
        "اذكر أن المستويات تقديرية ومقروءة من الصورة وليست أسعاراً لحظية. "
        "إذا لم تتوفر فرصة، ابدأ بـ 👑 أسطورة المجال | 🟡 انتظار."
    )
    payload = {
        "contents": [{
            "role": "user",
            "parts": [
                {"text": prompt},
                {"inline_data": {
                    "mime_type": mime,
                    "data": base64.b64encode(raw).decode("ascii")
                }},
            ],
        }],
        "generationConfig": {"maxOutputTokens": 550, "temperature": 0.2},
    }
    url = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        + GEMINI_MODEL + ":generateContent"
    )
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
    chunks = []
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                chunks.append(part["text"])
    answer = "\n".join(chunks).strip()
    if not answer:
        block = result.get("promptFeedback", {}).get("blockReason", "unknown")
        raise RuntimeError(f"Gemini returned no text; block reason: {block}")
    return answer


def handle_message(message: dict):
    chat = message.get("chat") or {}
    chat_type = chat.get("type")
    if chat_type not in ("private", "group", "supergroup"):
        return
    if chat_type in ("group", "supergroup") and ALLOWED_CHAT and str(chat.get("id")) != ALLOWED_CHAT:
        return
    photos = message.get("photo") or []
    if not photos:
        return
    chat_id = chat.get("id")
    message_id = message.get("message_id")
    try:
        raw, mime = download_photo(photos[-1]["file_id"])
        answer = analyze_image(raw, mime, message.get("caption", ""))
        send(chat_id, message_id, answer)
    except Exception as exc:
        error = str(exc)
        print(f"Photo processing failed: {type(exc).__name__}: {error}", flush=True)
        if "GEMINI_API_KEY is not configured" in error:
            user_error = "🔴 مفتاح Gemini غير مضاف في Railway. أضف GEMINI_API_KEY ضمن متغيرات الخدمة."
        elif "HTTP 400" in error or "HTTP 403" in error:
            user_error = "🔴 مفتاح Gemini أو صلاحية النموذج غير صحيحة. تحقق من المفتاح في Google AI Studio."
        elif "HTTP 429" in error:
            user_error = "🟠 وصلت إلى حد الاستخدام المجاني لـ Gemini أو حد الطلبات. انتظر تجدد الحصة ثم أعد المحاولة."
        elif "HTTP 404" in error:
            user_error = "🔴 نموذج Gemini غير متاح. تحقق من GEMINI_MODEL في Railway."
        elif "URLError" in type(exc).__name__ or "timed out" in error.lower():
            user_error = "🟠 تعذر الاتصال بخدمة التحليل مؤقتاً. حاول مجدداً بعد قليل."
        else:
            user_error = "🟡 تعذر تحليل الصورة. راجع سجلات Railway لمعرفة السبب."
        try:
            send(chat_id, message_id, user_error)
        except Exception as reply_exc:
            print(f"Telegram reply failed: {type(reply_exc).__name__}: {reply_exc}", flush=True)


def main():
    if not TOKEN:
        raise SystemExit("Missing TELEGRAM_BOT_TOKEN environment variable")
    if not GEMINI_API_KEY:
        raise SystemExit("Missing GEMINI_API_KEY environment variable")
    # Polling and webhook cannot run simultaneously for one Telegram bot token.
    telegram("deleteWebhook", {"drop_pending_updates": "false"})
    offset = None
    print(f"Telegram XAUUSD photo-analysis worker started. GEMINI_API_KEY configured: {bool(GEMINI_API_KEY)}; model: {GEMINI_MODEL}", flush=True)
    while True:
        try:
            params = {"timeout": 30, "allowed_updates": json.dumps(["message"])}
            if offset is not None:
                params["offset"] = offset
            updates = telegram("getUpdates", params, timeout=40)
            for update in updates:
                offset = int(update["update_id"]) + 1
                message = update.get("message") or {}
                handle_message(message)
        except Exception as exc:
            print(f"Polling error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
