from flask import Flask, request, jsonify
import os, requests, time, hmac, math

app = Flask(__name__)

# 🧠 Environment vars
BOT = os.getenv("BOT_TOKEN")
CHAT = os.getenv("CHAT_ID")
HEL_SECRET = os.getenv("HEL_SECRET") or os.getenv("HEL_WEBHOOK_SECRET") or "cryps_secret_943k29"

# ==========================
# 🔧 Telegram Sender
# ==========================
def send_tg(text):
    if not BOT or not CHAT: return
    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            params={"chat_id": CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=5
        )
    except Exception as e:
        app.logger.warning(f"[TG] send failed: {e}")

# ==========================
# 🤖 Cryps Ultra Core Logic
# ==========================
def cryps_score(tx):
    sol_value = tx.get("nativeTransfers", [{}])[0].get("amount", 0) / 1e9
    holders = len(tx.get("accounts", []))
    is_mint = tx.get("type") == "TOKEN_MINT"

    score = 0
    if sol_value > 5: score += 4
    if is_mint: score += 3
    if holders > 10: score += 2
    if tx.get("tokenTransfers"): score += 1

    # Normalize to 0→10
    return min(round(score, 1), 10)

# ==========================
# 🔗 Helius Webhook
# ==========================
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    # Secret check (3 modes)
    got = request.headers.get("X-Cryps-Secret") or request.args.get("secret") or ""
    if got != HEL_SECRET:
        app.logger.warning(f"[HEL] SECRET MISMATCH: got='{got}' expected='{HEL_SECRET}'")
        return ("unauthorized", 403)

    evt = request.get_json(silent=True) or {}
    txs = evt.get("transactions", [])
    if not txs:
        send_tg("⚙️ Test Webhook Received (no transactions)")
        return jsonify(ok=True)

    for tx in txs:
        sig = tx.get("signature", "")
        sol_value = tx.get("nativeTransfers", [{}])[0].get("amount", 0) / 1e9
        token = tx.get("tokenTransfers", [{}])[0].get("mint", "Unknown")
        tx_type = tx.get("type", "UNKNOWN")
        score = cryps_score(tx)

        # 🦈 Whale
        if sol_value >= 5:
            send_tg(f"🦈 *Whale Detected*\n💰 {sol_value:.2f} SOL\n🔗 [Solscan](https://solscan.io/tx/{sig})\n📊 CrypsScore: *{score}/10*")

        # ⚡ New Mint
        elif tx_type == "TOKEN_MINT":
            send_tg(f"⚡ *New Token Minted*\n🪙 {token}\n🔗 [Solscan](https://solscan.io/token/{token})\n📊 CrypsScore: *{score}/10*")

        # 💡 Winner hint (auto-detect)
        elif score >= 7:
            send_tg(f"🚀 *Winner Candidate Found*\n🔗 [Solscan](https://solscan.io/tx/{sig})\n📊 CrypsScore: *{score}/10*")

    return jsonify(ok=True)

# ==========================
# 💬 Telegram Commands
# ==========================
@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or {}).get("text", "").strip().lower()
    if not msg: return jsonify(ok=True)

    if msg in ["/start", "start"]:
        send_tg("✅ Cryps Ultra Pilot Online.\nCommands: /scan | /winners | /kinchi")

    elif msg in ["/scan", "scan"]:
        send_tg("🔍 *Cryps Ultra Scanner*\nScanning latest on-chain mints & whales...")

    elif msg in ["/kinchi", "kinchi"]:
        send_tg("📊 *Live Whale Heatmap*\nCollecting data from Helius feed...")

    elif msg in ["/winners", "winners"]:
        send_tg("🏆 *Top Winner Tokens* (last 24h)\n(coming soon module v1.1)")

    return jsonify(ok=True)

# ==========================
# 🏠 Home route
# ==========================
@app.route("/")
def home():
    return "Cryps Ultra Pilot on Render ✅"

# ==========================
# 🔥 Run
# ==========================
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", 10000)))


app.logger.info(f"[HEL] headers keys={list(request.headers.keys())}")
app.logger.info(f"[HEL] query secret present={bool(request.args.get('secret'))}")
