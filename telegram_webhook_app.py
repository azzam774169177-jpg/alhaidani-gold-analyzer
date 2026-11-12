#!/usr/bin/env python3
"""Telegram chart-photo analysis webhook using the OpenAI Responses API."""
from __future__ import annotations

import base64
import json
import os
import urllib.parse
import urllib.request

from flask import Flask, jsonify, request

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "-1003960644699").strip()
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip()
OPENAI_API_KEY = os.environ.get("OPENAI_API_KEY", "").strip()
OPENAI_MODEL = os.environ.get("OPENAI_MODEL", "gpt-6-astra").strip()


def telegram_api(method: str, params: dict | None = None, timeout: int = 25):
    if not TOKEN:
        raise RuntimeError("TELEGRAM_BOT_TOKEN is not configured")
    data = urllib.parse.urlencode(params or {}).encode()
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as response:
        result = json.loads(response.read().decode("utf-8"))
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram API error"))
    return result["result"]


def configure_webhook():
    if not TOKEN or not WEBHOOK_SECRET or not BASE_URL:
        print("Webhook not configured: missing Telegram or Render environment variables.")
        return
    result = telegram_api("setWebhook", {
        "url": BASE_URL.rstrip("/") + "/telegram-webhook",
        "secret_token": WEBHOOK_SECRET,
        "allowed_updates": json.dumps(["message"]),
        "drop_pending_updates": "false",
    })
    print("Telegram webhook configured: " + str(result))


def send_reply(chat_id: int, message_id: int, text: str):
    telegram_api("sendMessage", {
        "chat_id": str(chat_id),
        "reply_to_message_id": str(message_id),
        "text": text[:4000],
        "disable_web_page_preview": "true",
    })


def get_photo_bytes(file_id: str) -> bytes:
    info = telegram_api("getFile", {"file_id": file_id})
    file_path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    with urllib.request.urlopen(url, timeout=35) as response:
        return response.read()


def image_data_url(image_bytes: bytes) -> str:
    if image_bytes.startswith(b"\x89PNG\r\n\x1a\n"):
        mime = "image/png"
    elif image_bytes.startswith(b"RIFF") and image_bytes[8:12] == b"WEBP":
        mime = "image/webp"
    else:
        mime = "image/jpeg"
    return f"data:{mime};base64," + base64.b64encode(image_bytes).decode("ascii")


def analyze_with_openai(image_bytes: bytes, caption: str = "") -> str:
    if not OPENAI_API_KEY:
        raise RuntimeError("OPENAI_API_KEY is not configured")

    prompt = (
        "أنت محلل فني مساعد لصور شارت التداول. حلّل الصورة المرفقة بصرياً فقط. "
        "الأصل المطلوب XAUUSD (الذهب). استخدم نص العضو التالي كسياق إن وجد: "
        + (caption[:1000] if caption else "لا يوجد تعليق.")
        + "\nأولاً تحقق أن الصورة شارت تداول وأن الرمز XAUUSD ظاهر أو أن العضو ذكر XAUUSD. "
        "لا تخترع سعراً أو مؤشراً أو مستوى غير مقروء. لا تدّع امتلاك سعر لحظي أو بيانات خارج الصورة. "
        "إذا كانت الصورة غير واضحة، أو الرمز غير معروف، أو لا توجد فرصة فنية واضحة، أجب فقط بصيغة انتظار واذكر السبب. "
        "إذا كانت الفرصة واضحة، أخرج رداً عربياً قصيراً بهذا القالب: "
        "👑 أسطورة المجال | تحليل صورة الشارت\n"
        "🟢 BUY أو 🔴 SELL — XAUUSD\n"
        "منطقة الدخول: ...\nوقف الخسارة: ...\nالهدف الأول: ...\nالهدف الثاني: ...\n"
        "الهدف الثالث: ...\nسبب الإشارة: ...\n"
        "اذكر أن المستويات تقديرية من الصورة وليست سعراً لحظياً. لا تعطِ وعداً بالربح ولا تستخدم يقيناً مطلقاً. "
        "لا تخرج صفقة إذا تعذر تحديد دخول ووقف خسارة منطقيين من الصورة. "
        "في حالة الانتظار ابدأ بـ: 👑 أسطورة المجال | 🟡 انتظار."
    )
    payload = {
        "model": OPENAI_MODEL,
        "input": [{
            "role": "user",
            "content": [
                {"type": "input_text", "text": prompt},
                {"type": "input_image", "image_url": image_data_url(image_bytes), "detail": "high"},
            ],
        }],
        "max_output_tokens": 500,
    }
    req = urllib.request.Request(
        "https://api.openai.com/v1/responses",
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {OPENAI_API_KEY}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=75) as response:
        result = json.loads(response.read().decode("utf-8"))

    parts = []
    for item in result.get("output", []):
        if item.get("type") == "message":
            for content in item.get("content", []):
                if content.get("type") == "output_text" and content.get("text"):
                    parts.append(content["text"])
    answer = "\n".join(parts).strip()
    if not answer:
        raise RuntimeError("OpenAI returned no text output")
    return answer


@app.get("/")
def index():
    return jsonify({
        "service": "alhaidani-gold-photo-bot",
        "status": "online",
        "photo_analysis": "openai" if OPENAI_API_KEY else "waiting_for_openai_api_key",
        "trading_signals": "disabled",
    })


@app.get("/healthz")
def healthz():
    return jsonify({
        "ok": True,
        "photo_analysis": "openai" if OPENAI_API_KEY else "not_configured",
        "trading_signals": "disabled",
    })


@app.post("/telegram-webhook")
def telegram_webhook():
    if not TOKEN or not WEBHOOK_SECRET:
        return jsonify({"ok": False, "error": "bot_not_configured"}), 503
    if request.headers.get("X-Telegram-Bot-Api-Secret-Token", "") != WEBHOOK_SECRET:
        return jsonify({"ok": False}), 403

    update = request.get_json(silent=True) or {}
    message = update.get("message") or {}
    chat = message.get("chat") or {}
    photos = message.get("photo") or []

    chat_type = chat.get("type")
    if chat_type not in ("private", "group", "supergroup"):
        return jsonify({"ok": True})
    # Private chats are accepted from any member; group photos are limited
    # to the configured team group to avoid replying in unrelated groups.
    if chat_type in ("group", "supergroup") and ALLOWED_CHAT and str(chat.get("id")) != ALLOWED_CHAT:
        return jsonify({"ok": True})
    if not photos:
        return jsonify({"ok": True})

    try:
        if not OPENAI_API_KEY:
            send_reply(chat["id"], message["message_id"],
                       "🟡 تحليل الصور بالذكاء الاصطناعي غير مفعّل بعد. يرجى إبلاغ الإدارة بإضافة مفتاح الخدمة.")
            return jsonify({"ok": True})
        photo_bytes = get_photo_bytes(photos[-1]["file_id"])
        if len(photo_bytes) > 15 * 1024 * 1024:
            raise ValueError("image too large")
        answer = analyze_with_openai(photo_bytes, message.get("caption", ""))
        send_reply(chat["id"], message["message_id"], answer)
    except Exception as exc:
        print(f"Photo processing error: {type(exc).__name__}: {exc}")
        try:
            send_reply(chat["id"], message["message_id"],
                       "🟡 تعذر تحليل الصورة حالياً. أرسل لقطة واضحة للشارت وحاول مرة أخرى.")
        except Exception as send_exc:
            print(f"Reply error: {type(send_exc).__name__}: {send_exc}")
            return jsonify({"ok": False}), 500
    return jsonify({"ok": True})


if TOKEN and WEBHOOK_SECRET and BASE_URL:
    try:
        configure_webhook()
    except Exception as exc:
        print(f"Webhook setup error: {type(exc).__name__}: {exc}")
else:
    print("Waiting for Telegram/Render environment variables; trading signals remain disabled.")
