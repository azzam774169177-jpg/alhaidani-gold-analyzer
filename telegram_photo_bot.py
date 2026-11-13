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
ACCESS_PASSWORD = os.environ.get("BOT_ACCESS_PASSWORD", "AS7112026").strip()
AUTH_FILE = os.environ.get("BOT_AUTH_FILE", "authorized_users.json")


def load_authorized_users() -> set[int]:
    try:
        with open(AUTH_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        return {int(x) for x in data.get("authorized_user_ids", [])}
    except (FileNotFoundError, ValueError, TypeError, json.JSONDecodeError):
        return set()


def save_authorized_users(users: set[int]) -> None:
    temp = AUTH_FILE + ".tmp"
    with open(temp, "w", encoding="utf-8") as f:
        json.dump({"authorized_user_ids": sorted(users)}, f)
    os.replace(temp, AUTH_FILE)


AUTHORIZED_USERS = load_authorized_users()
# Collect member chart uploads briefly, then publish one consensus analysis.
BATCH_WINDOW_SECONDS = int(os.environ.get("PHOTO_BATCH_WINDOW_SECONDS", "90"))
PENDING_PHOTOS: list[tuple[bytes, str, str]] = []
PENDING_CHAT_ID = None
PENDING_REPLY_ID = None
PENDING_LAST_AT = 0.0
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

def send_plain(chat_id: int, message: str):
    telegram("sendMessage", {
        "chat_id": str(chat_id),
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


def analyze_images(images: list[tuple[bytes, str, str]]) -> str:
    if not GEMINI_API_KEY:
        raise RuntimeError("GEMINI_API_KEY is not configured")
    prompt = (
        "أنت محلل فني متخصص في الذهب XAUUSD. حلّل جميع صور الشارت المرفقة كمجموعة واحدة، وقد تكون من أعضاء مختلفين أو أطر زمنية مختلفة. "
        "استخرج المعلومات المشتركة فقط، وقارن الاتجاه والمستويات وبنية السوق بين الصور، ولا تعتبر تكرار الصورة تأكيداً مستقلاً. "
        "أصدر إشارة واحدة موحدة للجروب فقط إذا اتفقت الأدلة الفنية بدرجة كافية؛ وإلا أخرج انتظاراً. "
        "استخدم إطار تحليل احترافي متعدد الطبقات: (1) بنية السوق HH/HL أو LH/LL وتغير الشخصية CHoCH/BOS، "
        "(2) السيولة فوق القمم وتحت القيعان المتساوية، ورصد sweep ثم الإغلاق العائد داخل النطاق، "
        "(3) مناطق العرض والطلب وOrder Blocks مع اشتراط وجود displacement واضح، "
        "(4) فجوات القيمة العادلة FVG وعدم التوازن، (5) الاختراق الحقيقي مقابل fakeout ومصائد المشترين والبائعين، "
        "(6) موقع السعر بالنسبة إلى نطاق الجلسة والقمة/القاع القريبين إن ظهرا بالصورة. "
        "لا تفترض وجود خوارزمية سرية أو نية مؤكدة لصانع السوق؛ استنتج فقط سلوكاً محتملاً من حركة السعر الظاهرة. "
        "لا تعتبر أي منطقة وحدها سبباً كافياً للدخول: اطلب توافق عاملين أو أكثر وإشارة تأكيد واضحة مثل إغلاق/رفض/إعادة اختبار. "
        "إذا كانت الصورة لا تعرض سعراً أو فريماً مقروءاً، أو كانت الإشارات متضاربة، فالقرار انتظار. "
        "لا تدخل بعد حركة ممتدة أو شمعة اندفاعية متأخرة، ولا تقترح صفقة بعائد إلى مخاطرة أقل من 1:1.5 متى أمكن تقديره من الرسم. "
        "تعليقات الأعضاء المرفقة: " + " | ".join((caption[:300] if caption else "بدون تعليق") for _, _, caption in images)[:1500] + "\\n"
        "اقرأ الفريم الظاهر، وحدد الاتجاه BUY أو SELL فقط إذا وجدت فرصة فنية واضحة. "
        "استخرج سعر دخول محدداً، هدفاً واحداً واقعياً، ووقف خسارة واضحاً من مستويات الشارت. "
        "إذا كان الدخول يحتاج اختراقاً أو تأكيداً، اكتب شرط التفعيل بوضوح ولا تسمح بالدخول قبله. "
        "لا تختلق أسعاراً ولا تدّعِ أنك متصل بأسعار MT5 الحية. قرّب أسعار الذهب إلى أقرب عدد صحيح دون كسور. "
        "اجعل الهدف في اتجاه الصفقة ووقف الخسارة في الاتجاه المعاكس. لا تعطِ نسب نجاح أو ضمان ربح. "
        "أخرج الصفقة بهذا التنسيق حرفياً، واملأ الخانات بالأرقام المستخرجة من الصورة:\\n"
        "🟢 صفقة شراء الذهب XAUUSD 🥇 أو 🔴 صفقة بيع الذهب XAUUSD 🥇\\n"
        "🟢 الدخول: ...\\n"
        "🎯 هدفك: ...\\n"
        "🛑 استوبك: ...\\n"
        "إذا كانت الصفقة معلّقة، اكتب شرط التفعيل بجانب الدخول، وأضف سطراً واحداً: ❌ إلغاء الصفقة إذا: ...\\n"
        "إذا لم توجد فرصة واضحة، لا تكتفِ بذكر أن الاتجاه هابط أو صاعد. حدّد باختصار المستوى السعري الذي ننتظر وصول السعر إليه، وما التأكيد المطلوب بعده (مثل ارتداد من دعم، رفض مقاومة، اختراق وإغلاق فوق/تحت مستوى محدد). اذكر مستوى واحداً أو مستويين فقط إذا كانا واضحين بالصورة، ولا تخترع مستويات. استخدم الصيغة: 🟡 انتظار - ننتظر [السعر/المنطقة] ثم [شرط التأكيد] للدخول شراء/بيع. إذا تعذّر قراءة المستوى، قل ذلك بوضوح."
    )
    payload = {
        "contents": [{
            "role": "user",
            "parts": ([{"text": prompt}] + [
                {"inline_data": {
                    "mime_type": image_mime,
                    "data": base64.b64encode(image_raw).decode("ascii")
                }}
                for image_raw, image_mime, _caption in images
            ]),
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
    # Correct frequent Arabic trading-term spelling mistakes before sending.
    answer = answer.replace("شاعة", "شمعة").replace("شاعه", "شمعة")
    answer = answer.replace("اغلاق", "إغلاق").replace("اغلق", "أغلق")

    if not answer:
        block = result.get("promptFeedback", {}).get("blockReason", "unknown")
        raise RuntimeError(f"Gemini returned no text; block reason: {block}")
    # Display XAUUSD quote levels as whole numbers (no fractional cents).
    import re
    def whole_gold_price(match):
        value = float(match.group(0))
        return str(int(value + 0.5))
    answer = re.sub(r"(?<![\w])\d{3,5}\.\d+(?![\w])", whole_gold_price, answer)
    # Enforce nearest-to-farthest target order when all three target prices are numeric.
    target_labels = ["الهدف الأول", "الهدف الثاني", "الهدف الثالث"]
    target_pattern = re.compile(r"^(الهدف الأول|الهدف الثاني|الهدف الثالث):\s*([0-9]+(?:\.[0-9]+)?)\s*$", re.MULTILINE)
    target_matches = list(target_pattern.finditer(answer))
    if len(target_matches) == 3 and {m.group(1) for m in target_matches} == set(target_labels):
        direction = "BUY" if "BUY" in answer.upper() else ("SELL" if "SELL" in answer.upper() else "")
        if direction:
            prices = sorted((float(m.group(2)) for m in target_matches), reverse=(direction == "SELL"))
            for label, price in zip(target_labels, prices):
                answer = re.sub(
                    rf"^{re.escape(label)}:\s*[0-9]+(?:\.[0-9]+)?\s*$",
                    f"{label}: {int(price + 0.5)}",
                    answer,
                    count=1,
                    flags=re.MULTILINE,
                )
    return answer


def handle_message(message: dict):
    global AUTHORIZED_USERS, PENDING_LAST_AT
    chat = message.get("chat") or {}
    chat_type = chat.get("type")
    if chat_type not in ("private", "group", "supergroup"):
        return
    if chat_type in ("group", "supergroup") and ALLOWED_CHAT and str(chat.get("id")) != ALLOWED_CHAT:
        return

    chat_id = chat.get("id")
    message_id = message.get("message_id")
    sender_id = (message.get("from") or {}).get("id")
    text_message = (message.get("text") or "").strip()

    if chat_type == "private" and text_message:
        if text_message == ACCESS_PASSWORD:
            if sender_id is not None:
                AUTHORIZED_USERS.add(int(sender_id))
                save_authorized_users(AUTHORIZED_USERS)
            send(chat_id, message_id, "✅ تم تفعيل عضويتك بنجاح. أرسل صورة الشارت هنا لتحصل على تحليل خاص. ستُستخدم المؤشرات المستخلصة من الصورة أيضاً ضمن التحليل التجميعي للجروب، دون نشر صورتك أو اسمك.")
        else:
            send(chat_id, message_id, "🔒 للحصول على كلمة مرور تفعيل البوت، تواصل مع الإدارة عبر تيليجرام: @M77A77A")
        return

    photos = message.get("photo") or []
    if not photos:
        return
    if sender_id is None or int(sender_id) not in AUTHORIZED_USERS:
        if chat_type == "private":
            send(chat_id, message_id, "🔒 البوت محمي بكلمة مرور. للحصول على كلمة المرور، تواصل مع الإدارة: @M77A77A ثم أرسلها هنا لتفعيل حسابك.")
        else:
            send(chat_id, message_id, "🔒 التحليل محمي بكلمة مرور. للحصول على كلمة المرور تواصل مع الإدارة: @M77A77A، ثم أرسلها للبوت في الخاص وأعد إرسال الصورة.")
        return

    try:
        raw, mime = download_photo(photos[-1]["file_id"])
        caption = message.get("caption", "")
        if len(PENDING_PHOTOS) < 8:
            PENDING_PHOTOS.append((raw, mime, caption))
            PENDING_LAST_AT = time.time()
            print(f"Queued member chart for group consensus; batch size={len(PENDING_PHOTOS)}", flush=True)
        if chat_type == "private":
            answer = analyze_images([(raw, mime, caption)])
            send(chat_id, message_id, answer + "\n\n📊 تم إدراج المؤشرات الفنية المستخلصة من صورتك ضمن التحليل التجميعي للجروب دون مشاركة الصورة أو اسمك.")
        else:
            send(chat_id, message_id, "📥 تم استلام الشارت وإضافته للتحليل التجميعي. ستصل خلاصة الفرصة إلى الجروب بعد انتهاء فترة تجميع الصور.")
    except Exception as exc:
        error = str(exc)
        print(f"Photo processing failed: {type(exc).__name__}: {error}", flush=True)
        try:
            send(chat_id, message_id, "🟠 تعذر استلام الصورة أو تحليلها مؤقتاً. حاول مجدداً بعد قليل.")
        except Exception as reply_exc:
            print(f"Telegram reply failed: {type(reply_exc).__name__}: {reply_exc}", flush=True)



def flush_pending_photos(force: bool = False):
    global PENDING_PHOTOS, PENDING_LAST_AT
    if not PENDING_PHOTOS or (not force and time.time() - PENDING_LAST_AT < BATCH_WINDOW_SECONDS):
        return
    batch = PENDING_PHOTOS
    PENDING_PHOTOS = []
    PENDING_LAST_AT = 0.0
    try:
        print(f"Analyzing group consensus from {len(batch)} member chart image(s)", flush=True)
        answer = analyze_images(batch)
        if ALLOWED_CHAT:
            send_plain(int(ALLOWED_CHAT), "👑 أسطورة المجال | 📊 التحليل التجميعي لصور الأعضاء\n\n" + answer)
    except Exception as exc:
        print(f"Batch analysis failed: {type(exc).__name__}: {exc}", flush=True)
        if ALLOWED_CHAT:
            try:
                send_plain(int(ALLOWED_CHAT), "🟠 تعذر إكمال التحليل التجميعي لصور الأعضاء حالياً. حاولوا مجدداً بعد قليل.")
            except Exception as reply_exc:
                print(f"Telegram batch reply failed: {type(reply_exc).__name__}: {reply_exc}", flush=True)


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
                flush_pending_photos()
            flush_pending_photos()
        except Exception as exc:
            print(f"Polling error: {type(exc).__name__}: {exc}", flush=True)
            time.sleep(5)


if __name__ == "__main__":
    main()
