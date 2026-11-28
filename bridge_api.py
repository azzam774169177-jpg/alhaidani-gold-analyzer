"""Authenticated, durable command queue for the AZZAM711 MT5 bridge.

This service queues Telegram channel commands; it does NOT execute trades.
Railway terminates HTTPS. Keep BRIDGE_SHARED_SECRET private.
"""
from __future__ import annotations

import hmac
import json
import os
import sqlite3
import threading
from contextlib import contextmanager
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

DB_PATH = os.environ.get("BRIDGE_DB_PATH", "azzam711_bridge.sqlite3")
SECRET = os.environ.get("BRIDGE_SHARED_SECRET", "").strip()
MAX_AGE = int(os.environ.get("BRIDGE_MAX_SIGNAL_AGE", "180"))
DB_LOCK = threading.Lock()


@contextmanager
def db():
    conn = sqlite3.connect(DB_PATH, timeout=15)
    try:
        conn.row_factory = sqlite3.Row
        conn.execute("""
            CREATE TABLE IF NOT EXISTS commands (
                id TEXT PRIMARY KEY,
                created_at REAL NOT NULL,
                payload TEXT NOT NULL,
                acked_at REAL
            )
        """)
        conn.commit()
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def enqueue_command(command: dict) -> None:
    chat_id = str(command.get("telegram_chat_id", ""))
    message_id = str(command.get("telegram_message_id", ""))
    if not chat_id or not message_id:
        raise ValueError("Missing Telegram message identity")
    action = command.get("action")
    allowed = {"OPEN", "OPEN_DIRECT", "MOVE_SL_TO_ENTRY", "MOVE_SL", "LOCK_PROFIT",
               "CLOSE_POSITION", "CANCEL_PENDING", "SET_SL", "SET_TP",
               "SET_SL_ALL", "SET_TP_ALL"}
    if action not in allowed or command.get("symbol") != "XAUUSD":
        raise ValueError("Unsupported bridge command")
    if action == "OPEN_DIRECT" and command.get("side") not in {"BUY", "SELL"}:
        raise ValueError("Direct entry requires BUY or SELL side")
    if action in {"SET_SL", "SET_TP", "SET_SL_ALL", "SET_TP_ALL"}:
        try:
            price = float(command.get("price", 0))
        except (TypeError, ValueError):
            price = 0
        if price <= 0:
            raise ValueError("Stop/target update requires a positive price")
    key = chat_id + ":" + message_id
    with DB_LOCK, db() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO commands(id, created_at, payload) VALUES(?,?,?)",
            (key, time.time(), json.dumps(command, ensure_ascii=False)),
        )


class Handler(BaseHTTPRequestHandler):
    server_version = "AZZAM711Bridge/1.0"

    def log_message(self, fmt, *args):
        print("Bridge HTTP: " + (fmt % args), flush=True)

    def authorized(self):
        supplied = self.headers.get("Authorization", "")
        expected = "Bearer " + SECRET
        return bool(SECRET) and hmac.compare_digest(supplied, expected)

    def reply(self, status, obj):
        raw = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):
        path = urlparse(self.path).path
        if path == "/health":
            return self.reply(200, {"ok": True, "service": "AZZAM711 bridge queue"})
        if path != "/bridge/next":
            return self.reply(404, {"error": "not_found"})
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        now = time.time()
        with DB_LOCK, db() as conn:
            conn.execute(
                "UPDATE commands SET acked_at=? WHERE acked_at IS NULL AND created_at < ?",
                (now, now - MAX_AGE),
            )
            row = conn.execute(
                "SELECT id, created_at, payload FROM commands "
                "WHERE acked_at IS NULL ORDER BY created_at LIMIT 1"
            ).fetchone()
        if row is None:
            return self.reply(200, {"command": None})
        return self.reply(200, {
            "id": row["id"], "created_at": row["created_at"],
            "command": json.loads(row["payload"])
        })

    def do_POST(self):
        if urlparse(self.path).path != "/bridge/ack":
            return self.reply(404, {"error": "not_found"})
        if not self.authorized():
            return self.reply(401, {"error": "unauthorized"})
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length < 2 or length > 4096:
                return self.reply(400, {"error": "invalid_body"})
            body = json.loads(self.rfile.read(length).decode("utf-8"))
            command_id = str(body.get("id", ""))
            if not command_id or len(command_id) > 256:
                return self.reply(400, {"error": "invalid_id"})
            with DB_LOCK, db() as conn:
                cur = conn.execute(
                    "UPDATE commands SET acked_at=? WHERE id=? AND acked_at IS NULL",
                    (time.time(), command_id),
                )
            return self.reply(200, {"ok": True, "acknowledged": cur.rowcount == 1})
        except (ValueError, json.JSONDecodeError):
            return self.reply(400, {"error": "invalid_json"})


def start_bridge_server():
    port = int(os.environ.get("PORT", "8080"))
    server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
    thread = threading.Thread(target=server.serve_forever, name="bridge-http", daemon=True)
    thread.start()
    print(f"AZZAM711 bridge API listening on port {port}; secret configured={bool(SECRET)}", flush=True)
    return server
