import os, json, time
from flask import Flask, request, jsonify
import requests

# ============================================================
# 🔧 CONFIGURATION
# ============================================================
BOT_TOKEN = os.getenv("BOT_TOKEN", "PUT_YOUR_BOT_TOKEN_HERE")
CHAT_ID = os.getenv("CHAT_ID", "PUT_YOUR_CHAT_ID_HERE")
HEL_SEC = os.getenv("HEL_WEBHOOK_SECRET", "cryps_secret_943k29")

TOKENS_FILE = "data/tokens.json"
SIGNALS_FILE = "data/signals.log"
WHALES_FILE = "data/whales.txt"

# ============================================================
# 🧠 HELPERS
# ============================================================
app = Flask(__name__)

def now_ts():
    return int(time.time())

def send_tg(msg):
    try:
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
        requests.post(url, json={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"})
    except Exception as e:
        print("[TG ERROR]", e)

def read_whales():
    if not os.path.exists(WHALES_FILE):
        return []
    with open(WHALES_FILE, "r", encoding="utf-8") as f:
        return [x.strip() for x in f.readlines() if x.strip()]

def load_json(path, default=None):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default if default is not None else []

def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

# ============================================================
# 🤖 BOT COMMANDS
# ============================================================

@app.route(f"/{BOT_TOKEN}", methods=["POST"])
def tg_webhook():
    data = request.get_json()
    if not data:
        return jsonify({"ok": False})
    msg = data.get("message", {})
    chat = msg.get("chat", {}).get("id")
    text = msg.get("text", "")

    if chat != int(CHAT_ID):
        return jsonify({"ok": False})

    if text.startswith("/start"):
        send_tg("✅ *Cryps Ultra Pilot Online*\nCommands: `/scan` | `/winners` | `/kinchi`")
    elif text.startswith("/scan"):
        send_tg("🔍 *Cryps Ultra Scanner*\nScanning latest on-chain mints & whales…")
        scan_latest()
    elif text.startswith("/winners"):
        send_tg("🏆 *Top Winner Tokens (last 24h)*\n— module v1.1 coming next.")
    elif text.startswith("/kinchi"):
        kinchi_scan()
    else:
        send_tg("Unknown command.")

    return jsonify({"ok": True})

def scan_latest():
    tokens = load_json(TOKENS_FILE, [])
    if not tokens:
        send_tg("⚠️ No new tokens detected yet.")
        return
    latest = tokens[-1]
    mint = latest.get("mint")
    sol = latest.get("sol_value", 0)
    msg = f"⚡ *New Token Minted*\n`{mint}` • {sol:.2f} SOL\n🔗 https://solscan.io/token/{mint}"
    send_tg(msg)

def kinchi_scan():
    tokens = load_json(TOKENS_FILE, [])
    if not tokens:
        send_tg("😴 No data yet. Waiting for new mints...")
        return
    msg = "🔎 *Last 5 detected mints:*\n"
    for t in tokens[-5:]:
        msg += f"- `{t['mint']}` ({t['sol_value']:.2f} SOL)\n"
    send_tg(msg)

# ============================================================
# 🔔 HELIUS WEBHOOK
# ============================================================
@app.post("/hel-webhook")
def hel_webhook():
    secret = request.headers.get("X-Cryps-Secret") or request.args.get("secret")
    if secret != HEL_SEC:
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if not evt:
        return jsonify(error="no_json"), 400

    txs = evt.get("transactions", []) if isinstance(evt, dict) else evt

    try:
        with open(SIGNALS_FILE, "a", encoding="utf-8") as log:
            log.write(json.dumps(evt, ensure_ascii=False) + "\n")
    except Exception as e:
        print("[HEL] log error:", e)

    def _append_token(mint, sol_value, signature, ts):
        data = load_json(TOKENS_FILE, [])
        data.append({
            "mint": mint or "Unknown",
            "sol_value": float(sol_value or 0),
            "signature": signature or "",
            "ts": int(ts or now_ts()),
        })
        if len(data) > 10000:
            data = data[-10000:]
        save_json(TOKENS_FILE, data)

    whales = set(read_whales())
    n_mints = n_swaps = n_whale = 0

    for tx in (txs or []):
        try:
            sig = tx.get("signature") or tx.get("signatureId") or ""
            ttype = (tx.get("type") or "").upper()
            ts = int(tx.get("timestamp") or now_ts())

            sol_value = 0.0
            for nt in (tx.get("nativeTransfers") or []):
                amt = float(nt.get("amount") or 0)
                sol_value += (amt / 1e9) if amt > 1e6 else amt

            mint = None
            if tx.get("tokenTransfers"):
                mint = (tx["tokenTransfers"][0] or {}).get("mint")

            accs = [a.get("account") for a in (tx.get("accounts") or []) if a.get("account")]
            is_whale = any(a in whales for a in accs) if whales and accs else False

            if "MINT" in ttype and mint:
                _append_token(mint, sol_value, sig, ts)
                n_mints += 1
                send_tg(
                    f"⚡ *New Token Minted*\n`{mint}` • {sol_value:.2f} SOL\n"
                    f"🔗 [Solscan](https://solscan.io/token/{mint}) | [Tx](https://solscan.io/tx/{sig})"
                )

            if is_whale:
                n_whale += 1
                send_tg(
                    f"🐋 *Whale TX*\n🪙 `{mint or 'Unknown'}` • {sol_value:.2f} SOL\n"
                    f"🔗 https://solscan.io/tx/{sig}"
                )

            if "SWAP" in ttype:
                n_swaps += 1

        except Exception as e:
            print("[HEL] parse_error:", repr(e))

    if n_mints or n_swaps or n_whale:
        send_tg(f"📡 *Helius Feed*\nMints: *{n_mints}* • Swaps: *{n_swaps}* • Whales: *{n_whale}*")

    return jsonify(ok=True, parsed=len(txs or []), mints=n_mints, swaps=n_swaps, whales=n_whale)

# ============================================================
# 🚀 RUN APP
# ============================================================
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
