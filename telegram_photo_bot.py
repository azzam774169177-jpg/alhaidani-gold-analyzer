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
        "أنت محلل فني محترف لشارت الذهب XAUUSD. حلّل الصورة نفسها ولا تكتفِ بشرح عام. "
        "تعليق العضو: " + (caption[:800] if caption else "لا يوجد") + "\n"
        "حلّل كل الفريمات الظاهرة بما فيها M1 وM5 وM15 وM30 وH1 وH4 وD1، ولا ترفض M1 تلقائياً. "
        "استخرج السعر الحالي والمستويات فقط إذا كانت مقروءة فعلاً. افحص الاتجاه وبنية القمم والقيعان "
        "والدعم والمقاومة والشموع والزخم والمؤشرات الظاهرة فقط. لا تدّعِ بيانات حية أو اتصال MT5. "
        "المطلوب خطة تداول عملية: إذا ظهر اتجاه وإعداد واضح، اختر BUY أو SELL وحدد نوع التنفيذ "
        "(دخول مباشر أو أمر معلّق/دخول بعد اختراق أو إعادة اختبار)، وسعر التفعيل/منطقة الدخول، "
        "وقف الخسارة خلف نقطة إبطال فنية، وثلاثة أهداف عند مستويات ظاهرة. اجعل الأهداف والوقف متناسبة "
        "مع بنية الشارت ولا تستخدم أرقاماً ثابتة أو عشوائية. "
        "إذا لم يكتمل التأكيد لكن توجد مستويات واضحة، أعطِ سيناريو مشروطاً قابلاً للتنفيذ: "
        "اتجاه الصفقة، شرط التفعيل الدقيق، الدخول بعد تحقق الشرط، وقف الخسارة والأهداف، "
        "واكتب بوضوح أن الأمر لا يُفعّل قبل تحقق الشرط. "
        "لا تختلق أي سعر أو مستوى. إذا تعذر قراءة الأرقام أو لم توجد نقطة إبطال منطقية، "
        "اكتب انتظاراً مختصراً واذكر تحديداً ما ينقص؛ لا تجبر صفقة وهمية. "
        "لا تعطِ نسب نجاح أو ضمان ربح. أخرج الرد بالعربية وبلا مقدمات أو شرح مطوّل.\n"
        "عند وجود فرصة أو سيناريو مشروط استخدم هذا القالب فقط:\n"
        "👑 أسطورة المجال | 🟢 BUY أو 🔴 SELL XAUUSD\n"
        "الفريم: ...\nنوع الدخول: مباشر / معلّق / بعد التأكيد\n"
        "الدخول أو شرط التفعيل: ...\nوقف الخسارة: ...\n"
        "الهدف الأول: ...\nالهدف الثاني: ...\nالهدف الثالث: ...\n"
        "إلغاء الصفقة إذا: ...\n"
        "عند عدم وجود مستويات قابلة للقراءة استخدم فقط:\n"
        "👑 أسطورة المجال | 🟡 انتظار\nالفريم: ...\nالمستوى المطلوب للتفعيل: ...\n"
        "اكتب العربية سليمة إملائياً، وراجع النص قبل إرساله؛ استخدم كلمة التفعيل بشكل صحيح. "
        "كل أسعار الذهب يجب أن تظهر أعداداً صحيحة بلا كسور أو سنتات، مثل 3888 وليس 3888.652. "
        "رتّب أهداف الشراء تصاعدياً من الأقرب إلى الأبعد، وأهداف البيع تنازلياً من الأقرب إلى الأبعد. "
        "تأكد أن الهدف الأول هو الأقرب للدخول ثم الثاني ثم الثالث، وأن وقف الخسارة في الجهة المعاكسة. "
        "لا تغيّر ترتيب مستويات السوق ولا تخترع أرقاماً؛ قرّب الأسعار المقروءة إلى أقرب عدد صحيح."
        "لا تضع أرقاماً تقريبية غير مقروءة من الصورة."
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
    def call_model(model_name: str):
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            + model_name + ":generateContent"
        )
        req = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_API_KEY},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=90) as response:
            return json.loads(response.read().decode("utf-8"))

    def discover_vision_model():
        # Ask Google's Models API which models this exact API key can use.
        url = "https://generativelanguage.googleapis.com/v1beta/models?pageSize=1000"
        req = urllib.request.Request(url, headers={"x-goog-api-key": GEMINI_API_KEY})
        with urllib.request.urlopen(req, timeout=30) as response:
            listing = json.loads(response.read().decode("utf-8"))
        available = {
            item.get("name", "").removeprefix("models/"): item
            for item in listing.get("models", [])
            if "generateContent" in item.get("supportedGenerationMethods", [])
            and item.get("name", "").removeprefix("models/") != GEMINI_MODEL
        }
        # Prefer current, low-cost multimodal Flash models, but only if this key lists them.
        preferences = [
            "gemini-3.5-flash-lite",
            "gemini-3.8-flash",
            "gemini-3.5-flash",
            "gemini-3.7-flash",
            "gemini-3.6-flash",
            "gemini-3.1-flash-lite",
            "gemini-2.5-flash",
            "gemini-2.5-flash-lite",
        ]
        for name in preferences:
            if name in available:
                return name
        # Last resort: a listed Flash model that supports generateContent.
        for name in available:
            low = name.lower()
            if "flash" in low and not any(x in low for x in ("audio", "tts", "image", "transcribe", "live")):
                return name
        raise RuntimeError(
            "No compatible Flash vision model is listed for this API key. "
            "Models returned: " + ", ".join(list(available)[:30])
        )

    selected_model = GEMINI_MODEL
    try:
        result = call_model(selected_model)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:1200]
        if exc.code != 404:
            raise RuntimeError(f"Gemini API HTTP {exc.code}: {detail}") from exc
        # The configured model may not be enabled for this project. Discover one the key can use.
        try:
            selected_model = discover_vision_model()
            print(f"Configured Gemini model unavailable; retrying with listed model: {selected_model}", flush=True)
            result = call_model(selected_model)
        except urllib.error.HTTPError as retry_exc:
            retry_detail = retry_exc.read().decode("utf-8", errors="replace")[:1200]
            raise RuntimeError(f"Gemini fallback HTTP {retry_exc.code}: {retry_detail}") from retry_exc
        except Exception as discovery_exc:
            raise RuntimeError(f"Gemini model discovery failed: {type(discovery_exc).__name__}: {discovery_exc}") from discovery_exc
    chunks = []
    for candidate in result.get("candidates", []):
        for part in candidate.get("content", {}).get("parts", []):
            if part.get("text"):
                chunks.append(part["text"])
    answer = "\n".join(chunks).strip()
    if not answer:
        block = result.get("promptFeedback", {}).get("blockReason", "unknown")
        raise RuntimeError(f"Gemini returned no text; block reason: {block}")
    # Display XAUUSD quote levels as whole numbers (no fractional cents).
    import re
    def whole_gold_price(match):
        value = float(match.group(0))
        return str(int(value + 0.5))
    answer = re.sub(r"(?<![\w])\d{3,5}\.\d+(?![\w])", whole_gold_price, answer)
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
    print(f"Telegram XAUUSD photo-analysis worker started. GEMINI_API_KEY configured: {bool(GEMINI_API_KEY)}; configured model: {GEMINI_MODEL}", flush=True)
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
