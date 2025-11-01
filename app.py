# app.py
from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

BOT = os.getenv("BOT_TOKEN")
CHAT = os.getenv("CHAT_ID")

# نقرا السر من HEL_WEBHOOK_SECRET (أو HEL_SECRET باش نغطّيو الحالتين)
HEL_SECRET = os.getenv("HEL_WEBHOOK_SECRET") or os.getenv("HEL_SECRET") or "cryps_secret_943k29"

TG_API = "https://api.telegram.org/bot{}/sendMessage".format(BOT)

def send_tg(text):
    if not (BOT and CHAT):
        return
    try:
        requests.get(
            TG_API,
            params={"chat_id": CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=6,
        )
    except Exception:
        pass

@app.route("/")
def home():
    return "Cryps Listener on Render ✅"

# ـ Telegram bot webhook
@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or {}).get("text", "") or ""
    txt = msg.strip().lower()

    if txt in ("/start", "start"):
        send_tg("✅ *Cryps Listener online.*\nCommands: /scan")
    elif txt in ("/scan", "scan"):
        send_tg("🤖 Got: Scan")
    elif txt in ("kinchi", "/kinchi"):
        send_tg("🤖 Got: Kinchi")

    return jsonify(ok=True), 200

# ـ Helius webhook (واحد فقط!)
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook_listener():
    # تحقق من السرّ
    secret = request.headers.get("X-Cryps-Secret")
    if secret != HEL_SECRET:
        return jsonify({"error": "unauthorized"}), 403

    payload = request.get_json(silent=True) or {}

    # Helius Enhanced webhooks: كنلقاو لائحة transactions
    txs = payload.get("transactions") or []
    for tx in txs:
        sig = tx.get("signature")

        # SOL value (إن وُجد)—nativeTransfers كيكون بلامات/lamports
        sol_value = 0.0
        try:
            native = (tx.get("nativeTransfers") or [{}])[0]
            sol_value = float(native.get("amount", 0)) / 1e9
        except Exception:
            pass

        # نوع الترانزاكسيون
        tx_type = tx.get("type", "")

        # Mint address (إن وُجد)
        mint = None
        try:
            mint = (tx.get("tokenTransfers") or [{}])[0].get("mint")
        except Exception:
            pass

        # 🦈 Whale filter
        if sol_value and sol_value > 5:
            send_tg(
                f"🦈 *Whale Detected!*\n"
                f"💰 {sol_value:.2f} SOL\n"
                f"🔗 https://solscan.io/tx/{sig}"
            )

        # ⚡ New mint
        if tx_type == "TOKEN_MINT" and mint:
            send_tg(
                f"⚡ *New Token Minted*\n"
                f"🪙 Mint: `{mint}`\n"
                f"🔗 https://solscan.io/token/{mint}"
            )

    # رجّع OK بسرعة (Helius خاصو 2xx)
    return jsonify({"status": "ok"}), 200
