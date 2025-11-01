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
