from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = os.getenv("CHAT_ID")
SECRET = os.getenv("HEL_WEBHOOK_SECRET", "")
TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"

def send_tg(text, chat_id=CHAT_ID):
    try:
        requests.post(f"{TELEGRAM_API}/sendMessage",
                      json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"})
    except Exception as e:
        print("Telegram send error:", e)

@app.route("/", methods=["GET"])
def home():
    return "Cryps Listener on Render ✅"

@app.route("/hel-webhook", methods=["POST"])
def helius_webhook():
    # أمان: تأكد من السر
    if SECRET and request.headers.get("X-Cryps-Secret") != SECRET:
        return jsonify({"ok": False, "error": "Invalid Secret"}), 401

    data = request.get_json(silent=True) or {}
    tx_type = data.get("type", "unknown")
    preview = str(data)[:500]
    msg = f"🟢 <b>Helius Event</b>\nType: <code>{tx_type}</code>\n\n{preview}"
    send_tg(msg)
    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "8080")))
