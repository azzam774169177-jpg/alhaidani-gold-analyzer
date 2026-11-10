#!/usr/bin/env python3
"""Telegram photo-analysis webhook for Render Free Web Services.

This service only inspects chart screenshots with the existing experimental
OpenCV analyzer. It never creates, sends, or executes trading signals.
"""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

from flask import Flask, jsonify, request
from photo_chart_analyzer import analyze_chart_image

app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
ALLOWED_CHAT = os.environ.get("TELEGRAM_ALLOWED_CHAT_ID", "-1003960644699").strip()
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET", "").strip()
BASE_URL = os.environ.get("RENDER_EXTERNAL_URL", "").strip()


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
        print("Webhook not configured: set TELEGRAM_BOT_TOKEN and TELEGRAM_WEBHOOK_SECRET.")
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
        "text": text,
        "disable_web_page_preview": "true",
    })


def get_photo_bytes(file_id: str) -> bytes:
    info = telegram_api("getFile", {"file_id": file_id})
    file_path = info["file_path"]
    url = f"https://api.telegram.org/file/bot{TOKEN}/{file_path}"
    with urllib.request.urlopen(url, timeout=35) as response:
        return response.read()


def format_result(result: dict) -> str:
    if result.get("status") == "WAIT":
        return "👑 أسطورة المجال | فحص الشارت\n🟡 انتظار\n" + result.get("reason", "الصورة غير كافية للفحص.")
    direction = "🟢" if result.get("status") == "UP" else "🔴"
    return (
        "👑 أسطورة المجال | فحص الشارت\n"
        f"{direction} {result.get('bias', 'قراءة غير حاسمة')}\n"
        f"🟢 بكسلات خضراء: {result.get('green_share', 0)}%\n"
        f"🔴 بكسلات حمراء: {result.get('red_share', 0)}%\n"
        "⚠️ فحص بصري تجريبي للألوان فقط؛ ليس تحليلاً احترافياً ولا توصية أو إشارة دخول."
    )


@app.get("/")
def index():
    return jsonify({"service": "alhaidani-gold-photo-bot", "status": "online", "trading_signals": "disabled"})


@app.get("/healthz")
def healthz():
    return jsonify({"ok": True, "photo_analysis": "experimental", "trading_signals": "disabled"})


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

    if chat.get("type") not in ("group", "supergroup"):
        return jsonify({"ok": True})
    if ALLOWED_CHAT and str(chat.get("id")) != ALLOWED_CHAT:
        return jsonify({"ok": True})
    if not photos:
        return jsonify({"ok": True})

    try:
        photo_bytes = get_photo_bytes(photos[-1]["file_id"])
        result = analyze_chart_image(photo_bytes)
        send_reply(chat["id"], message["message_id"], format_result(result))
    except Exception as exc:
        print(f"Photo processing error: {type(exc).__name__}: {exc}")
        try:
            send_reply(chat["id"], message["message_id"], "🟡 تعذر فحص الصورة حالياً. أعد إرسال لقطة واضحة للشارت.")
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
    print("Waiting for Render environment variables; trading signals remain disabled.")
