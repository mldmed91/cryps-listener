import os, json, re
from pathlib import Path
from flask import Flask, request, jsonify
from dotenv import load_dotenv
import requests
from datetime import datetime

# ===== Boot =====
load_dotenv()
app = Flask(__name__)

DATA_DIR = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)
TOKENS_JSON = DATA_DIR / "tokens.json"
WHALES_TXT  = DATA_DIR / "whales.txt"
SIGNALS_LOG = DATA_DIR / "signals.log"

# defaults
if not TOKENS_JSON.exists(): TOKENS_JSON.write_text("[]", encoding="utf-8")
if not WHALES_TXT.exists():  WHALES_TXT.write_text("", encoding="utf-8")
if not SIGNALS_LOG.exists(): SIGNALS_LOG.write_text("", encoding="utf-8")

# ===== ENV =====
BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID     = os.getenv("CHAT_ID", "").strip()
TG_SECRET   = os.getenv("TG_SECRET", "").strip()    # query param secret for /tg-webhook
HELIUS_SEC  = os.getenv("HELIUS_SECRET", "").strip()
AUTO_MODE   = (os.getenv("AUTO_MODE", "false").lower() == "true")
BASE_URL    = os.getenv("BASE_URL", "").strip()

# ===== Helpers =====
def now():
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")

def send_tg(text, chat_id=None, disable_preview=False):
    """Simple Telegram sender (no lib)."""
    if not BOT_TOKEN:
        print("[TG] BOT_TOKEN missing")
        return
    chat_id = chat_id or CHAT_ID
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": chat_id,
            "text": text,
            "disable_web_page_preview": disable_preview,
            "parse_mode": "HTML",
        }, timeout=10)
        if r.status_code != 200:
            print("[TG-ERR]", r.text)
    except Exception as e:
        print("[TG-EXC]", e)

def read_whales():
    return [ln.strip() for ln in WHALES_TXT.read_text(encoding="utf-8").splitlines() if ln.strip()]

def add_whale(addr):
    addr = addr.strip()
    if not re.fullmatch(r"[1-9A-HJ-NP-Za-km-z]{32,44}", addr):
        return False, "❌ address format not valid"
    whales = set(read_whales())
    if addr in whales:
        return False, "ℹ️ address already in whales list"
    whales.add(addr)
    WHALES_TXT.write_text("\n".join(sorted(whales)), encoding="utf-8")
    return True, "✅ whale added"

def remove_whale(addr):
    whales = set(read_whales())
    if addr in whales:
        whales.remove(addr)
        WHALES_TXT.write_text("\n".join(sorted(whales)), encoding="utf-8")
        return True, "✅ whale removed"
    return False, "ℹ️ address not found"

def load_tokens():
    try:
        return json.loads(TOKENS_JSON.read_text(encoding="utf-8"))
    except:
        return []

def save_tokens(arr):
    TOKENS_JSON.write_text(json.dumps(arr, ensure_ascii=False, indent=2), encoding="utf-8")

def log_signal(line):
    with open(SIGNALS_LOG, "a", encoding="utf-8") as f:
        f.write(f"[{now()}] {line}\n")

def solscan_token(mint):   return f"https://solscan.io/token/{mint}"
def solscan_tx(sig):       return f"https://solscan.io/tx/{sig}"
def dexscreener(mint):     return f"https://dexscreener.com/solana/{mint}"

# ===== Routes =====
@app.get("/healthz")
def health(): return "ok", 200

# --- Telegram webhook (secure by query ?secret=TG_SECRET)
@app.post("/tg-webhook")
def tg_webhook():
    if TG_SECRET and request.args.get("secret") != TG_SECRET:
        return jsonify({"error": "forbidden"}), 403

    upd = request.get_json(silent=True) or {}
    msg = (upd.get("message") or upd.get("edited_message")) or {}
    text = (msg.get("text") or "").strip()
    chat_id = msg.get("chat", {}).get("id") or CHAT_ID

    if not text:
        return jsonify({"ok": True})

    # Commands
    if text.startswith("/start"):
        send_tg(
            "✅ <b>Cryps Ultra Pilot Online</b>\n"
            "Commands:\n"
            "• /scan – ydir snapshot manual\n"
            "• /winners – top winners (24h)\n"
            "• /kinchi – snapshot mints & whales\n"
            "• /whales – list\n"
            "Admin:\n"
            "• /whale_add &lt;addr&gt;\n"
            "• /whale_remove &lt;addr&gt;\n"
            "⚠️ AUTO_MODE: <b>OFF</b> (on-demand only)\n", chat_id)
        return jsonify({"ok": True})

    if text.startswith("/whales"):
        whales = read_whales()
        if not whales:
            send_tg("Whales List: (empty)", chat_id)
        else:
            out = "\n".join([f"{i+1}. <code>{a}</code>" for i, a in enumerate(whales)])
            send_tg(f"Whales List:\n{out}", chat_id, disable_preview=True)
        return jsonify({"ok": True})

    if text.startswith("/whale_add"):
        parts = text.split()
        if len(parts) < 2:
            send_tg("Usage: /whale_add <WALLET_ADDRESS>", chat_id)
        else:
            ok, msg2 = add_whale(parts[1])
            send_tg(msg2, chat_id)
        return jsonify({"ok": True})

    if text.startswith("/whale_remove"):
        parts = text.split()
        if len(parts) < 2:
            send_tg("Usage: /whale_remove <WALLET_ADDRESS>", chat_id)
        else:
            ok, msg2 = remove_whale(parts[1])
            send_tg(msg2, chat_id)
        return jsonify({"ok": True})

    if text.startswith("/kinchi"):
        send_tg("🔎 Cryps Ultra Scanner\nScanning latest on-chain mints & whales…", chat_id)
        # purely cosmetic – real feed comes from Helius → /hel-webhook
        return jsonify({"ok": True})

    if text.startswith("/scan"):
        send_tg("🛰️ Live Whale Heatmap\nCollecting signals from Helius…", chat_id)
        # manual scan is symbolic here (no node calls) – feed=webhook
        return jsonify({"ok": True})

    if text.startswith("/winners"):
        toks = load_tokens()
        if not toks:
            send_tg("🏆 Top Winner Tokens (last 24h)\n— module v1.1 coming next.", chat_id)
        else:
            # show up to 10
            lines = []
            for t in toks[:10]:
                lines.append(f"• <b>{t.get('symbol','?')}</b>\n"
                             f"<code>{t.get('mint')}</code>\n"
                             f"<a href=\"{solscan_token(t['mint'])}\">Solscan</a> | "
                             f"<a href=\"{dexscreener(t['mint'])}\">DexScreener</a>")
            send_tg("🏆 Top Winner Tokens (24h)\n" + "\n\n".join(lines), chat_id)
        return jsonify({"ok": True})

    # fallback
    send_tg("ℹ️ Commands: /scan /winners /kinchi /whales", chat_id)
    return jsonify({"ok": True})

# --- Helius webhook (Enhanced), secured by header X-Cryps-Secret or ?secret=
@app.post("/hel-webhook")
def hel_webhook():
    secret = request.headers.get("X-Cryps-Secret") or request.args.get("secret")
    if HELIUS_SEC and secret != HELIUS_SEC:
        return jsonify({"error": "unauthorized"}), 403

    evt = request.get_json(silent=True)
    if not evt:
        return jsonify({"error": "no_json"}), 400

    txs = evt.get("transactions", []) if isinstance(evt, dict) else evt
    whales = set(read_whales())
    n_whales = 0
    n_mints  = 0

    for tx in txs:
        try:
            sig  = tx.get("signature") or tx.get("signature", "")
            typ  = tx.get("type") or ""
            sol  = float(tx.get("sol", 0.0))
            accs = set([a.get("account") for a in tx.get("accounts", []) if a.get("account")])

            # whale detection
            if whales and any(a in whales for a in accs):
                n_whales += 1
                send_tg(f"🐋 <b>Whale Detected</b>\n{sol:.2f} SOL\n"
                        f"<a href=\"{solscan_tx(sig)}\">Solscan</a>", disable_preview=True)
                log_signal(f"WHLE sig={sig} sol={sol}")

            # mint detection (best-effort):
            # Helius enhanced often puts 'TOKEN_MINT' or has 'tokenTransfers'
            mint = None
            if typ == "TOKEN_MINT":
                n_mints += 1
                # try find mint address
                tt = tx.get("tokenTransfers") or []
                if tt and isinstance(tt, list):
                    mint = tt[0].get("mint")
            else:
                tt = tx.get("tokenTransfers") or []
                for t in tt:
                    if t.get("type") == "MINT":
                        mint = t.get("mint")
                        n_mints += 1
                        break

            if mint:
                # save quick entry
                tokens = load_tokens()
                tokens.insert(0, {"mint": mint, "symbol": tx.get("symbol","?"), "ts": now()})
                tokens = tokens[:100]  # keep last 100
                save_tokens(tokens)

                msg = (f"⚡ <b>New Token Minted</b>\n"
                       f"<code>{mint}</code>\n"
                       f"<a href=\"{solscan_token(mint)}\">Solscan</a> | "
                       f"<a href=\"{dexscreener(mint)}\">DexScreener</a>\n"
                       f"CrypsScore: 4/10")
                send_tg(msg, disable_preview=False)
                log_signal(f"MINT mint={mint} sig={sig}")

        except Exception as err:
            print("ERR:", err)

    # end summary
    if (n_mints + n_whales) > 0:
        send_tg(f"🪙 Feed: {n_mints} mints, {n_whales} whale txs", disable_preview=True)
    else:
        # ما كنصيفطوش بزاف باش مانصرفوش الكريدي، غير واحد المرة فالأمر
        print(f"[HEL] Feed: {n_mints} mints, {n_whales} whale txs")

    return jsonify({"ok": True})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
