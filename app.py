from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

# ===== Config (من الـ env على Render) =====
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
HEL_SECRET = os.getenv("HEL_WEBHOOK_SECRET", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

# ===== Helpers =====
def send_tg(text, chat_id=CHAT_ID):
    if not BOT_TOKEN or not chat_id:
        print("BOT_TOKEN or CHAT_ID missing")
        return
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"},
                      timeout=10)
    except Exception as e:
        print("Telegram send error:", e)

# Solo admin only
ALLOWED_ADMIN_IDS = {int(CHAT_ID)} if CHAT_ID else set()
def is_admin(chat_id):
    try:
        return int(chat_id) in ALLOWED_ADMIN_IDS
    except:
        return False

# ===== Routes =====
@app.route("/", methods=["GET"])
def home():
    return "Cryps Listener on Render ✅"

# Telegram webhook (باش البوت يجاوبك فـ الشات)
@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = data.get("message") or data.get("edited_message") or {}
    chat = msg.get("chat") or {}
    chat_id = chat.get("id")
    text = (msg.get("text") or "").strip()

    if not is_admin(chat_id):
        return jsonify({"ok": True})

    if text in ("/start", "/status"):
        send_tg("✅ Cryps Listener online.\nCommands: /scan", chat_id)
    elif text.startswith("/scan"):
        send_tg("🔎 Scan OK (placeholder). Listener working.", chat_id)
    else:
        send_tg(f"🤖 Got: {text}", chat_id)
    return jsonify({"ok": True})

# Helius webhook (الأحداث من سولانا)
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    if HEL_SECRET and request.headers.get("X-Cryps-Secret") != HEL_SECRET:
        return jsonify({"ok": False, "error": "Invalid Secret"}), 401
    data = request.get_json(silent=True) or {}
    tx_type = data.get("type", "unknown")
    preview = str(data)[:500]
    msg = f"🟢 <b>Helius Event</b>\nType: <code>{tx_type}</code>\n\n{preview}\n\n🔒 Analytics only — not financial advice."
    send_tg(msg)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
