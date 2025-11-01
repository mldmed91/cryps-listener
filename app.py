from flask import Flask, request, jsonify
import os, requests, hmac

app = Flask(__name__)

BOT = os.getenv("BOT_TOKEN")
CHAT = os.getenv("CHAT_ID")
HEL_SECRET = os.getenv("HEL_SECRET") or os.getenv("HEL_WEBHOOK_SECRET") or "cryps_secret_943k29"

def send_tg(text):
    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            params={"chat_id": CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=5
        )
    except:
        pass

@app.route("/")
def home():
    return "Cryps Listener on Render ✅"

@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or {}).get("text", "").strip().lower()
    if msg in ["/start", "start"]:
        send_tg("✅ Cryps Listener online.\nCommands: /scan")
    elif msg in ["/scan", "scan"]:
        send_tg("🤖 Got: Scan")
    elif msg in ["kinchi", "/kinchi"]:
        send_tg("🤖 Got: Kinchi")
    return jsonify(ok=True)

@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    incoming = request.headers.get("X-Cryps-Secret", "")
    # Log للمقارنة (ما كيبينش السرّ كامل فـ اللوجز)
    app.logger.info(f"[HEL] header len={len(incoming)} expected len={len(HEL_SECRET)}")

    # مقارنة آمنة
    if not hmac.compare_digest(incoming, HEL_SECRET or ""):
        # عطيني السبب فـ اللوجز باش نعرفو الفرق
        app.logger.warning(f"[HEL] SECRET MISMATCH: got={repr(incoming)} expected={repr(HEL_SECRET)}")
        return ("unauthorized", 403)

    evt = request.get_json(silent=True) or {}
    app.logger.info(f"[HEL] OK payload keys={list(evt.keys())[:5]} ...")
    # هنا تقدر تزيد المعالجة ديال CREATE / SWAP / TOKEN_MINT ...
    return jsonify(ok=True)
