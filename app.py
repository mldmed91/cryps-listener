# app.py — Cryps Ultra Pilot (Render + Flask + Telegram + Helius)
from flask import Flask, request, jsonify
import os, requests

app = Flask(__name__)

# ====== ENV ======
BOT  = os.getenv("BOT_TOKEN", "").strip()
CHAT = os.getenv("CHAT_ID", "").strip()
HEL_SECRET = (os.getenv("HEL_SECRET") or os.getenv("HEL_WEBHOOK_SECRET") or "cryps_secret_943k29").strip()

# ====== TG SENDER ======
def send_tg(text):
    if not BOT or not CHAT: 
        app.logger.warning("[TG] Missing BOT_TOKEN or CHAT_ID")
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            params={"chat_id": CHAT, "text": text, "parse_mode": "Markdown"},
            timeout=8
        )
    except Exception as e:
        app.logger.warning(f"[TG] send failed: {e}")

# ====== SIMPLE SCORE ======
def cryps_score(tx, sol_value, has_mint, acc_count, has_token_transfer):
    score = 0
    if sol_value > 5: score += 4
    if has_mint: score += 3
    if acc_count > 10: score += 2
    if has_token_transfer: score += 1
    return min(round(score, 1), 10)

# ====== HELPERS ======
def _first(d, *paths, default=None):
    """Try multiple dot-paths in dict-like obj. Returns first non-empty."""
    for p in paths:
        try:
            cur = d
            for key in p.split("."):
                if isinstance(cur, dict):
                    cur = cur.get(key)
                else:
                    cur = None
                    break
            if cur not in (None, "", []):
                return cur
        except Exception:
            pass
    return default

def parse_tx(tx):
    """Normalize Helius tx variations safely."""
    if not isinstance(tx, dict):
        return {
            "signature": "unknown",
            "sol_value": 0.0,
            "token_mint": "Unknown",
            "tx_type": "UNKNOWN",
            "acc_count": 0,
            "has_token_transfer": False,
            "is_mint": False
        }

    signature = (
        tx.get("signature")
        or _first(tx, "transaction.signature", default="unknown")
        or "unknown"
    )

    # nativeTransfers could be list/dict/absent
    native = tx.get("nativeTransfers") or []
    if isinstance(native, dict): native = [native]
    lamports = 0
    if native and isinstance(native[0], dict):
        lamports = native[0].get("amount", 0) or native[0].get("lamports", 0) or 0
    sol_value = float(lamports) / 1e9

    # tokenTransfers could be list/dict/absent
    token_mint = "Unknown"
    tts = tx.get("tokenTransfers") or []
    if isinstance(tts, dict): tts = [tts]
    if tts and isinstance(tts[0], dict):
        token_mint = tts[0].get("mint") or tts[0].get("tokenAddress") or "Unknown"
    has_token_transfer = bool(tts)

    tx_type = (
        tx.get("type")
        or tx.get("activityType")
        or _first(tx, "events.type", default="UNKNOWN")
        or "UNKNOWN"
    )
    is_mint = (tx_type == "TOKEN_MINT")

    accs = tx.get("accounts") or []
    if isinstance(accs, dict): accs = [accs]
    acc_count = len(accs) if isinstance(accs, list) else 0

    return {
        "signature": signature,
        "sol_value": sol_value,
        "token_mint": token_mint,
        "tx_type": tx_type,
        "acc_count": acc_count,
        "has_token_transfer": has_token_transfer,
        "is_mint": is_mint
    }

def solscan_tx(sig):   return f"https://solscan.io/tx/{sig}"
def solscan_token(m):  return f"https://solscan.io/token/{m}"
def dexscreener_token(m): return f"https://dexscreener.com/solana/{m}"

# ====== ROUTES ======
@app.route("/")
def home():
    return "Cryps Ultra Pilot on Render ✅"

@app.route("/healthz")
def healthz():
    return "ok", 200

# Telegram webhook (commands)
@app.route("/tg-webhook", methods=["POST"])
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = (data.get("message") or {}).get("text", "")
    msg_low = (msg or "").strip().lower()

    if not msg_low:
        return jsonify(ok=True)

    if msg_low in ("/start", "start"):
        send_tg("✅ *Cryps Ultra Pilot Online*\nCommands: `/scan` | `/winners` | `/kinchi`")
    elif msg_low in ("/scan", "scan"):
        send_tg("🔍 *Cryps Ultra Scanner*\nScanning latest on-chain mints & whales…")
    elif msg_low in ("/kinchi", "kinchi"):
        send_tg("📊 *Live Whale Heatmap*\nCollecting signals from Helius…")
    elif msg_low in ("/winners", "winners"):
        send_tg("🏆 *Top Winner Tokens* (last 24h)\n— module v1.1 coming next.")
    else:
        send_tg("🤖 Commands: `/scan` | `/winners` | `/kinchi`")
    return jsonify(ok=True)

# Helius webhook (accepts: Header, Bearer, or ?secret=)
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    expected = HEL_SECRET or ""

    # 1) X-Cryps-Secret header
    got = request.headers.get("X-Cryps-Secret", "").strip()

    # 2) Authorization: Bearer <secret>
    if not got:
        auth = (request.headers.get("Authorization") or "").strip()
        if auth.lower().startswith("bearer "):
            got = auth.split(" ", 1)[1].strip()

    # 3) ?secret=...
    if not got:
        got = (request.args.get("secret") or "").strip()

    if got != expected:
        app.logger.warning(f"[HEL] SECRET MISMATCH: got='{got}' expected='{expected}'")
        return ("unauthorized", 403)

    data = request.get_json(silent=True)
    if data is None:
        app.logger.warning("[HEL] No JSON body")
        send_tg("⚙️ Test Webhook Received (empty)")
        return jsonify(ok=True), 200

    # Normalize into list of txs
    if isinstance(data, list):
        txs = data
    elif isinstance(data, dict):
        txs = data.get("transactions") or data.get("events") or []
        if isinstance(txs, dict):  # sometimes single object
            txs = [txs]
    else:
        txs = []

    if not txs:
        send_tg("⚙️ Test Webhook Received (no transactions)")
        return jsonify(ok=True), 200

    # Process every tx safely
    for raw in txs:
        try:
            p = parse_tx(raw)
            sig, solv, mint, ttype = p["signature"], p["sol_value"], p["token_mint"], p["tx_type"]
            score = cryps_score(raw, solv, p["is_mint"], p["acc_count"], p["has_token_transfer"])

            # Alerts
            if solv >= 5:
                send_tg(
                    f"🦈 *Whale Detected*\n"
                    f"💰 {solv:.2f} SOL\n"
                    f"🔗 [Solscan]({solscan_tx(sig)})\n"
                    f"📊 CrypsScore: *{score}/10*"
                )
            elif ttype == "TOKEN_MINT":
                send_tg(
                    f"⚡ *New Token Minted*\n"
                    f"🪙 {mint}\n"
                    f"🔗 [Solscan]({solscan_token(mint)}) | [DexScreener]({dexscreener_token(mint)})\n"
                    f"📊 CrypsScore: *{score}/10*"
                )
            elif score >= 7:
                send_tg(
                    f"🚀 *Winner Candidate Found*\n"
                    f"🔗 [Solscan]({solscan_tx(sig)})\n"
                    f"📊 CrypsScore: *{score}/10*"
                )

        except Exception as e:
            app.logger.warning(f"[HEL] tx parse error: {e}")

    return jsonify(ok=True), 200

# ====== LOCAL RUN ======
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
