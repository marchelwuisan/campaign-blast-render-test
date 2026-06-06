import os
import sqlite3
from datetime import datetime, timezone

from flask import Flask, request

app = Flask(__name__)

# A token YOU invent — must match the verify token entered in the Meta dashboard.
VERIFY_TOKEN = os.getenv("WA_VERIFY_TOKEN", "wa_verify_token")
DB_PATH = os.getenv("DB_PATH", "Pipeline/database/wa_blast.db")

OPT_OUT_KEYWORD = "STOP"


def is_opt_out(content: str) -> bool:
    return content.strip().upper() == OPT_OUT_KEYWORD


def flag_unsubscribe(sender: str) -> int:
    # Meta sends `sender` without a "+" prefix (e.g. "6282123501897"),
    # while `customer.phone_number` is stored with the prefix ("+62..."),
    # so compare digits only.
    digits = sender.lstrip("+")
    with sqlite3.connect(DB_PATH) as conn:
        cursor = conn.execute(
            "UPDATE customer SET is_unsubscribe = 1 WHERE REPLACE(phone_number, '+', '') = ?",
            (digits,),
        )
        return cursor.rowcount


def init_db():
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS incoming_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender TEXT NOT NULL,
                content TEXT,
                received_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS outgoing_messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                recipient TEXT NOT NULL,
                sent_at TEXT NOT NULL
            )
        """)


def save_incoming_message(sender: str, content: str, received_at: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO incoming_messages (sender, content, received_at) VALUES (?, ?, ?)",
            (sender, content, received_at),
        )


def save_outgoing_message(recipient: str, sent_at: str):
    with sqlite3.connect(DB_PATH) as conn:
        conn.execute(
            "INSERT INTO outgoing_messages (recipient, sent_at) VALUES (?, ?)",
            (recipient, sent_at),
        )


init_db()


@app.get("/webhook")
def verify():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == VERIFY_TOKEN:
        return challenge, 200  # echo the challenge back as plain text
    return "Forbidden", 403


@app.post("/webhook")
def receive():
    data = request.get_json(silent=True) or {}

    try:
        value = data["entry"][0]["changes"][0]["value"]
    except (KeyError, IndexError):
        print("[webhook] unrecognized payload:", data)
        return "OK", 200

    for msg in value.get("messages", []):
        sender = msg.get("from")
        msg_type = msg.get("type")
        text = msg.get("text", {}).get("body", "")

        ts = msg.get("timestamp")
        if ts:
            received_at = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat()
        else:
            received_at = datetime.now(timezone.utc).isoformat()

        save_incoming_message(sender, text, received_at)
        print(f"[webhook] message from {sender} ({msg_type}) at {received_at}: {text}")

        if msg_type == "text" and is_opt_out(text):
            updated = flag_unsubscribe(sender)
            print(f"[webhook] opt-out from {sender}: flagged {updated} customer row(s)")

    for status in value.get("statuses", []):
        wamid = status.get("id")
        status_val = status.get("status")
        print(f"[webhook] status {wamid}: {status_val}")

        if status_val == "sent":
            recipient = status.get("recipient_id", "")
            ts = status.get("timestamp")
            sent_at = datetime.fromtimestamp(int(ts), tz=timezone.utc).isoformat() if ts else datetime.now(timezone.utc).isoformat()
            save_outgoing_message(recipient, sent_at)
            print(f"[webhook] logged outgoing to {recipient} at {sent_at}")

    return "OK", 200


@app.get("/")
def health():
    return "ok", 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 5000)))
