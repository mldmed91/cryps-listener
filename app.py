# app.py — Cryps Ultra Pilot v1.4 (Helius Sync Enabled)
from flask import Flask, request, jsonify
import os, json, time, datetime as dt, requests

app = Flask(__name__)

# ====== ENVIRONMENT ======
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = os.getenv("CHAT_ID", "")
HEL_SECRET = os.getenv("HEL_SECRET", "cryps_secret_943k29")

HELIUS_API = os.getenv("HELIUS_API_KEY", "")
HELIUS_WID = os.getenv("HELIUS_WEBHOOK_ID", "")
PUBLIC_URL = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")

# ====== FILES ======
DATA_DIR = "data"
TOKENS_FILE = os.path.join(DATA_DIR, "tokens.json")
SIGNALS_FILE = os.path.join(DATA_DIR, "signals.log")
WHALES_FILE = os.path.join(DATA_DIR, "whales.txt")
RAY_FILE = os.path.join(DATA_DIR, "raydium_pools.json")

os.makedirs(DATA_DIR, exist_ok=True)
for f, default in [
    (TOKENS_FILE, []),
    (SIGNALS_FILE, ""),
    (WHALES_FILE, ""),
    (RAY_FILE, []),
]:
    if not os.path.exists(f):
        with open(f, "w", encoding="utf-8") as out:
            if isinstance(default, list):
                json.dump(default, out)
            else:
                out.write(default)

# ====== HELPERS ======
def now_ts():
    return int(time.time())

def send_tg(msg: str):
    if not (BOT_TOKEN and CHAT_ID): return
    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": msg, "parse_mode": "Markdown"},
            timeout=8
        )
    except: pass

def log(msg: str):
    try:
        with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.utcnow().isoformat()}Z | {msg}\n")
    except: pass

def read_whales():
    try:
        with open(WHALES_FILE, "r", encoding="utf-8") as f:
            return [l.strip() for l in f if l.strip()]
    except: return []

def write_whales(lst):
    with open(WHALES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(lst))

def add_whale(addr):
    whales = read_whales()
    if addr not in whales:
        whales.append(addr)
        write_whales(whales)
        return True
    return False

def remove_whale(addr):
    whales = read_whales()
    if addr in whales:
        whales.remove(addr)
        write_whales(whales)
        return True
    return False

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return default

def save_json(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
    except:
        pass

# ====== HELIUS SYNC ======
def helius_sync_addresses():
    """يحدّث العناوين عند Helius"""
    if not (HELIUS_API and HELIUS_WID and PUBLIC_URL):
        return False, "HELIUS envs missing"
    addrs = read_whales()
    payload = {
        "webhookURL": f"{PUBLIC_URL}/hel-webhook?secret={HEL_SECRET}",
        "transactionTypes": ["ANY"],
        "accountAddresses": addrs,
        "webhookType": "enhanced"
    }
    url = f"https://api.helius.xyz/v0/webhooks/{HELIUS_WID}?api-key={HELIUS_API}"
    try:
        r = requests.put(url, json=payload, timeout=10)
        ok = r.status_code in (200, 201)
        log(f"[HELIUS] Sync {len(addrs)} addresses -> {r.status_code}")
        return ok, r.text
    except Exception as e:
        log(f"[HELIUS] Sync error {e}")
        return False, str(e)

# ====== ROUTES ======
@app.get("/")
def home():
    return "✅ Cryps Ultra Pilot v1.4 — Active"

@app.get("/sync-helius")
def sync_helius():
    ok, msg = helius_sync_addresses()
    return jsonify(ok=ok, msg=msg, whales=len(read_whales()))

# ====== TELEGRAM ======
@app.post("/tg-webhook")
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = ((data.get("message") or {}).get("text") or "").strip()
    low = msg.lower()

    if low in ("/start", "start"):
        send_tg("✅ *Cryps Ultra Pilot Online*\nCommands: `/scan`, `/winners`, `/kinchi`, `/whales`\nAdmin: `/whale_add <addr>`, `/whale_remove <addr>`")
        return jsonify(ok=True)

    if low in ("/scan", "scan"):
        send_tg("🔎 *Cryps Ultra Scanner*\nScanning latest on-chain mints & whales…")
        return jsonify(ok=True)

    if low in ("/kinchi", "kinchi"):
        send_tg("📊 *Live Whale Heatmap*\nCollecting signals from Helius…")
        return jsonify(ok=True)

    if low in ("/winners", "winners"):
        db = load_json(TOKENS_FILE, [])
        if not db:
            send_tg("🏆 *Top Winner Tokens (24h)*\nNo data yet.")
            return jsonify(ok=True)
        lines = ["🏆 *Top Winner Tokens (24h)*"]
        recent = [d for d in db if d.get("ts", 0) > now_ts() - 86400]
        top = sorted(recent, key=lambda x: x.get("sol_value", 0), reverse=True)[:10]
        for i, t in enumerate(top, 1):
            lines.append(f"{i}. `{t.get('mint')}` • {t.get('sol_value', 0):.2f} SOL\n🔗 https://solscan.io/tx/{t.get('signature')}")
        send_tg("\n".join(lines))
        return jsonify(ok=True)

    if low in ("/whales", "whales"):
        whales = read_whales()
        if not whales:
            send_tg("No whales yet.")
        else:
            send_tg("*Whales List:* \n" + "\n".join([f"{i+1}. `{a}`" for i,a in enumerate(whales)]))
        return jsonify(ok=True)

    if low.startswith("/whale_add"):
        parts = msg.split()
        if len(parts) >= 2:
            ok = add_whale(parts[1])
            send_tg(f"➕ Added whale: `{parts[1]}`" if ok else "Already exists or invalid.")
            helius_sync_addresses()
        else:
            send_tg("Usage: `/whale_add <WALLET_ADDRESS>`")
        return jsonify(ok=True)

    if low.startswith("/whale_remove"):
        parts = msg.split()
        if len(parts) >= 2:
            ok = remove_whale(parts[1])
            send_tg(f"➖ Removed whale: `{parts[1]}`" if ok else "Not found.")
            helius_sync_addresses()
        else:
            send_tg("Usage: `/whale_remove <WALLET_ADDRESS>`")
        return jsonify(ok=True)

    return jsonify(ok=True)

# ====== HELIUS WEBHOOK ======
@app.post("/hel-webhook")
def hel_webhook():
    secret = request.args.get("secret") or request.headers.get("X-Cryps-Secret")
    if secret != HEL_SECRET:
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if not evt:
        return jsonify(error="no_json"), 400

    txs = evt.get("transactions", []) if isinstance(evt, dict) else evt
    whales = set(read_whales())

    n_whales = n_mints = 0
    db = load_json(TOKENS_FILE, [])

    for tx in txs:
        try:
            sig = tx.get("signature", "")
            ttype = tx.get("type", "").upper()
            ts = int(tx.get("timestamp", now_ts()))
            sol_value = sum([(nt.get("amount", 0)/1e9) for nt in tx.get("nativeTransfers", []) or []])
            mint = None
            if tx.get("tokenTransfers"):
                mints = [t.get("mint") for t in tx["tokenTransfers"] if t.get("mint")]
                mint = mints[0] if mints else None
            accounts = [a.get("account") for a in tx.get("accounts", []) or []]
            if any(a in whales for a in accounts):
                n_whales += 1
                send_tg(f"🐋 Whale TX • {sol_value:.2f} SOL\n🪙 `{mint}`\n🔗 https://solscan.io/tx/{sig}")
            if "MINT" in ttype:
                n_mints += 1
            db.append({"signature": sig, "mint": mint, "sol_value": sol_value, "ts": ts})
        except Exception as e:
            log(f"[HEL] parse error {e}")

    save_json(TOKENS_FILE, db[-1000:])
    send_tg(f"📡 Feed: {n_mints} mints, {n_whales} whale txs")
    return jsonify(ok=True)

# ====== MAIN ======
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
