# app.py (خلاصة سكيليتون)
from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

BOT = os.getenv("BOT_TOKEN"); CHAT = os.getenv("CHAT_ID")
HEL_SECRET = os.getenv("HEL_SECRET", "cryps_secret_943k29")

def send_tg(text):
    try:
        requests.get(f"https://api.telegram.org/bot{BOT}/sendMessage",
                     params={"chat_id": CHAT, "text": text, "parse_mode":"Markdown"})
    except: pass

@app.route("/")
def home():
    return "Cryps Listener on Render ✅"

@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    data = request.get_json(force=True) or {}
    msg = (data.get("message") or {}).get("text","").strip().lower()
    if msg in ["/start", "start"]:
        send_tg("✅ Cryps Listener online.\nCommands: /scan")
    elif msg in ["/scan", "scan"]:
        send_tg("🤖 Got: Scan")
    elif msg in ["kinchi","/kinchi"]:
        send_tg("🤖 Got: Kinchi")
    return jsonify(ok=True)

@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    if request.headers.get("X-Cryps-Secret") != HEL_SECRET:
        return ("", 403)
    evt = request.get_json(force=True) or {}
    # تقدّر تزائد: parsing للسواب/المينت + send_tg على الإشارات
    return jsonify(ok=True)

@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    secret = request.headers.get("X-Cryps-Secret")
    if secret != HEL_SECRET:
        return jsonify({"error": "unauthorized"}), 403

    data = request.json
    if not data: 
        return jsonify({"status": "no_data"}), 400

    for tx in data.get("transactions", []):
        sig = tx.get("signature")
        accounts = [a.get("account") for a in tx.get("accounts", [])]
        token = tx.get("tokenTransfers", [{}])[0].get("mint", "Unknown")
        sol_value = tx.get("nativeTransfers", [{}])[0].get("amount", 0) / 1e9

        # Whale Alert Filter
        if sol_value > 5:
            send_tg(f"🦈 Whale Detected!\n💰 {sol_value:.2f} SOL\n🔗 https://solscan.io/tx/{sig}")

        # New Mint Detector
        if tx.get("type") == "TOKEN_MINT":
            send_tg(f"⚡ New Token Minted\n🪙 Mint: {token}\n🔗 https://solscan.io/token/{token}")

    return jsonify({"status": "ok"}), 200
