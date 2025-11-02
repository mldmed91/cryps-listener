# pilot module
from pilot.pilot import ingest_txn, pilot_add_event, pilot_top_winners

# Cryps Ultra Pilot v1.2 — full ready version
from flask import Flask, request, jsonify
import os, json, time, datetime as dt, requests
from pilot.pilot import ingest_txn, pilot_add_event, pilot_top_winners

app = Flask(__name__)

# ====== ENV ======
BOT  = os.getenv("BOT_TOKEN", "")
CHAT = os.getenv("CHAT_ID", "")
HEL_SEC = os.getenv("HEL_WEBHOOK_SECRET", "cryps_secret_943k29")

# ====== DATA PATHS ======
DATA_DIR = "data"
TOKENS_FILE  = os.path.join(DATA_DIR, "tokens.json")
WHALES_FILE  = os.path.join(DATA_DIR, "whales.txt")
SIGNALS_FILE = os.path.join(DATA_DIR, "signals.log")

os.makedirs(DATA_DIR, exist_ok=True)

# ====== INIT FILES ======
if not os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump({"tokens": {}, "events": []}, f)
if not os.path.exists(WHALES_FILE):
    open(WHALES_FILE, "w").close()
if not os.path.exists(SIGNALS_FILE):
    open(SIGNALS_FILE, "w").close()

# ====== HELPERS ======
def send_tg(msg: str):
    if not (BOT and CHAT): return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT}/sendMessage",
            params={"chat_id": CHAT, "text": msg, "parse_mode":"Markdown"})
    except Exception: pass

def read_whales():
    try:
        with open(WHALES_FILE, "r", encoding="utf-8") as f:
            return [x.strip() for x in f if x.strip()]
    except: return []

def now(): return int(time.time())

# ====== ROUTES ======
@app.get("/")
def home(): return "✅ Cryps Ultra Pilot running!"

@app.get("/healthz")
def health(): return jsonify(ok=True, ts=now(), whales=len(read_whales()))

@app.post("/tg-webhook")
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = ((data.get("message") or {}).get("text") or "").strip().lower()

    if msg in ("/start", "start"):
        send_tg("✅ *Cryps Ultra Pilot Active*\nCommands: `/scan`, `/winners`, `/kinchi`, `/whales`")
        return jsonify(ok=True)

    if msg in ("/winners", "winners"):
        winners = pilot_top_winners()
        if not winners:
            send_tg("🏆 *No winners yet*")
            return jsonify(ok=True)
        lines = ["🏆 *Top Winner Tokens (24h)*"]
        for i, r in enumerate(winners[:10], 1):
            lines.append(f"{i}. `{r['mint']}` • Score {r['score']} • 🦈 {r['whale_in']} • {r['sol_in']} SOL")
            lines.append(f"https://solscan.io/token/{r['mint']}")
        send_tg("\n".join(lines))
        return jsonify(ok=True)

    if msg in ("/whales", "whales"):
        whales = read_whales()
        send_tg("No whales yet." if not whales else "\n".join(whales))
        return jsonify(ok=True)

    if msg in ("/kinchi", "kinchi"):
        send_tg("📡 Collecting live whale activity…")
        return jsonify(ok=True)

    return jsonify(ok=True)

# ====== HELIUS WEBHOOK ======
@app.post("/hel-webhook")
def hel_webhook():
    secret = request.headers.get("X-Cryps-Secret") or request.args.get("secret")
    if secret != HEL_SEC:
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if not evt: return jsonify(error="no_json"), 400
    txs = evt.get("transactions", []) if isinstance(evt, dict) else evt

    whales = set(read_whales())
    n_whales = n_mints = 0

    for tx in txs:
        try:
            e = ingest_txn(tx)
            pilot_add_event(e)

            mint = e.get("mint")
            sol = e.get("sol", 0.0)
            typ = e.get("type", "")
            accs = set(e.get("accounts", []))
            if any(a in whales for a in accs):
                n_whales += 1
                send_tg(f"🦈 Whale TX detected!\n🪙 `{mint}` • {sol:.2f} SOL\n🔗 https://solscan.io/tx/{e['sig']}")
            elif "MINT" in typ:
                n_mints += 1
                send_tg(f"⚡ New Mint: `{mint}`\n🔗 https://solscan.io/token/{mint}")

        except Exception as err:
            print("ERR:", err)

    send_tg(f"📡 Feed: {n_mints} new mints • {n_whales} whale txs")
    return jsonify(ok=True)

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
