
# app.py — Cryps Ultra Pilot (Manual Mode, no spam)
# -----------------------------------------------
import os, json, time, logging
from pathlib import Path
from typing import List, Dict, Any, Tuple
import requests
from flask import Flask, request, jsonify

# ========= ENV & PATHS =========
BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID     = os.getenv("CHAT_ID", "").strip()          # اختياري؛ إذا خليتو فارغ يرد فالغروب/الشات اللي وصّلو
HEL_SECRET  = os.getenv("HEL_SECRET", "").strip()       # نفس اللي فـ Helius Webhook
ADMIN_IDS   = {x.strip() for x in os.getenv("ADMIN_IDS", "").split(",") if x.strip()}

DATA_DIR    = Path("data")
DATA_DIR.mkdir(parents=True, exist_ok=True)

WHALES_PATH = DATA_DIR / "whales.txt"
TOKENS_PATH = DATA_DIR / "tokens.json"
LOG_PATH    = DATA_DIR / "signals.log"

# ========= LOGGING =========
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(message)s"
)
log = logging.getLogger("cryps")

# ========= TELEGRAM =========
def tg_api(method: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if not BOT_TOKEN:
        log.warning("BOT_TOKEN missing; Telegram send skipped.")
        return {"ok": False}
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=payload, timeout=10)
        return r.json()
    except Exception as e:
        log.error(f"TG send failed: {e}")
        return {"ok": False}

def send_tg(text: str, chat_id: str = None, disable_preview: bool = True):
    """Send markdown message; default to CHAT_ID if set."""
    cid = chat_id or CHAT_ID
    payload = {"chat_id": cid, "text": text, "parse_mode": "Markdown", "disable_web_page_preview": disable_preview}
    return tg_api("sendMessage", payload)

# ========= STORAGE HELPERS =========
def ensure_files():
    if not WHALES_PATH.exists():
        WHALES_PATH.write_text("", encoding="utf-8")
    if not TOKENS_PATH.exists():
        TOKENS_PATH.write_text("{}", encoding="utf-8")
    if not LOG_PATH.exists():
        LOG_PATH.write_text("", encoding="utf-8")

def read_whales() -> List[str]:
    ensure_files()
    addrs = []
    for line in WHALES_PATH.read_text(encoding="utf-8").splitlines():
        s = line.strip()
        if s and not s.startswith("#"):
            addrs.append(s)
    return addrs

def write_whales(addrs: List[str]):
    WHALES_PATH.write_text("\n".join(addrs) + ("\n" if addrs else ""), encoding="utf-8")

def append_log(line: str):
    with LOG_PATH.open("a", encoding="utf-8") as f:
        f.write(line.rstrip() + "\n")

def upsert_token_event(mint: str, event: Dict[str, Any]):
    try:
        db = json.loads(TOKENS_PATH.read_text(encoding="utf-8") or "{}")
    except Exception:
        db = {}
    arr = db.get(mint, [])
    arr.append(event)
    db[mint] = arr[-100:]  # keep last 100
    TOKENS_PATH.write_text(json.dumps(db, ensure_ascii=False, indent=2), encoding="utf-8")

# ========= HELIUS PARSER =========
def _num(v, default=0.0):
    try:
        return float(v)
    except Exception:
        return default

def ingest_tx(tx: Dict[str, Any]) -> Dict[str, Any]:
    """
    Parse Helius Enhanced Tx.
    Returns: {sig, type, mint, sol, accounts}
    """
    sig   = tx.get("signature") or tx.get("sig") or ""
    typ   = tx.get("type") or ""
    accts = [a.get("account") for a in tx.get("accounts", []) if isinstance(a, dict) and a.get("account")]
    # SOL moved (rough)
    sol_amount = 0.0
    for t in tx.get("nativeTransfers", []) or []:
        sol_amount += _num(t.get("amount", 0)) / 1e9
    # token mint address (if TOKEN_MINT or tokenTransfers present)
    mint = ""
    if typ == "TOKEN_MINT":
        # Some payloads put the mint at tokenTransfers[0].mint
        if tx.get("tokenTransfers"):
            mint = (tx["tokenTransfers"][0] or {}).get("mint", "")
    else:
        # fallback: if swap/transfer includes a tokenTransfers field, grab first mint
        if tx.get("tokenTransfers"):
            mint = (tx["tokenTransfers"][0] or {}).get("mint", "")

    return {"sig": sig, "type": typ, "mint": mint, "sol": round(sol_amount, 8), "accounts": accts or []}

def check_whale_hit(accounts: List[str], whales_set: set) -> bool:
    return any(a in whales_set for a in accounts)

# ========= FLASK APP =========
app = Flask(__name__)

@app.get("/healthz")
def health():
    return jsonify(ok=True, mode="manual")

# ---- Telegram webhook (optional if مستعمل Webhook) ----
@app.post("/tg-webhook")
def tg_webhook():
    upd = request.get_json(silent=True) or {}
    msg = (upd.get("message") or upd.get("edited_message")) or {}
    text = (msg.get("text") or "").strip()
    chat_id = str((msg.get("chat") or {}).get("id", "")) or CHAT_ID
    uid = str((msg.get("from") or {}).get("id", ""))

    def is_admin() -> bool:
        return (not ADMIN_IDS) or (uid in ADMIN_IDS)

    if text.startswith("/start"):
        send_tg("✅ *Cryps Ultra Pilot Online*\nCommands: `/scan`, `/winners`, `/kinchi`, `/whales`\nAdmin: `/whale_add <addr>`, `/whale_remove <addr>`", chat_id)
        return jsonify(ok=True)

    if text.startswith("/whales"):
        lst = read_whales()
        pretty = "\n".join([f"{i+1}. `{a}`" for i, a in enumerate(lst)]) or "_No whales yet._"
        send_tg(f"*Whales List:*\n{pretty}", chat_id)
        return jsonify(ok=True)

    if text.startswith("/whale_add"):
        if not is_admin():
            send_tg("❌ Not allowed.", chat_id); return jsonify(ok=True)
        parts = text.split()
        if len(parts) < 2: 
            send_tg("Usage: `/whale_add <WALLET_ADDRESS>`", chat_id); return jsonify(ok=True)
        addr = parts[1].strip()
        lst = read_whales()
        if addr in lst:
            send_tg("ℹ️ Already in list.", chat_id)
        else:
            lst.append(addr); write_whales(lst)
            send_tg("✅ Added.\nUse `/whales` to view.", chat_id)
        return jsonify(ok=True)

    if text.startswith("/whale_remove"):
        if not is_admin():
            send_tg("❌ Not allowed.", chat_id); return jsonify(ok=True)
        parts = text.split()
        if len(parts) < 2:
            send_tg("Usage: `/whale_remove <WALLET_ADDRESS>`", chat_id); return jsonify(ok=True)
        addr = parts[1].strip()
        lst = read_whales()
        if addr not in lst:
            send_tg("ℹ️ Address not found.", chat_id)
        else:
            lst = [x for x in lst if x != addr]; write_whales(lst)
            send_tg("✅ Removed.\nUse `/whales` to view.", chat_id)
        return jsonify(ok=True)

    if text.startswith("/scan"):
        send_tg("🔎 *Cryps Ultra Scanner*\nScanning latest on-chain mints & whales…", chat_id)
        # Manual mode: we don't force-pull. We rely on Helius webhook to push events.
        return jsonify(ok=True)

    if text.startswith("/kinchi"):
        send_tg("📊 *Live Whale Heatmap*\nCollecting signals from Helius…", chat_id)
        return jsonify(ok=True)

    if text.startswith("/winners"):
        # Placeholder — إقرا top من tokens.json
        try:
            db = json.loads(TOKENS_PATH.read_text(encoding="utf-8") or "{}")
            # ترتيب حسب عدد الأحداث
            top = sorted(db.items(), key=lambda kv: len(kv[1]), reverse=True)[:10]
            if not top:
                send_tg("🏆 *Top Winner Tokens (last 24h)*\n— module v1.1 coming next.", chat_id)
            else:
                lines = []
                for mint, events in top:
                    lines.append(f"- `{mint}` · {len(events)} events")
                send_tg("🏆 *Top Winner Tokens (24h)*\n" + "\n".join(lines), chat_id)
        except Exception as e:
            log.error(f"/winners error: {e}")
            send_tg("🏆 *Top Winner Tokens (24h)*\n— module v1.1 coming next.", chat_id)
        return jsonify(ok=True)

    return jsonify(ok=True)

# ---- Helius webhook ----
@app.post("/hel-webhook")
def hel_webhook():
    # Secret check
    secret = request.headers.get("X-Cryps-Secret") or request.args.get("secret") or ""
    if HEL_SECRET and secret != HEL_SECRET:
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if not evt:
        # لا تبعث حتى شيء — منع السبام
        log.warning("[HEL] No JSON body")
        return jsonify(ok=True, note="no_json")

    # Helius may send list OR object with 'transactions'
    txs = []
    if isinstance(evt, dict):
        txs = evt.get("transactions", []) or []
    elif isinstance(evt, list):
        txs = evt
    else:
        txs = []

    if not txs:
        # لا ترسل Feed 0 — هذا كان سبب السبام
        return jsonify(ok=True, note="no_txs")

    whales_set = set(read_whales())
    n_mints = 0
    n_whales = 0

    for tx in txs:
        try:
            e = ingest_tx(tx)
            upsert_token_event(e.get("mint") or e.get("sig") or "unknown", e)

            is_whale = check_whale_hit(e.get("accounts", []), whales_set)
            if is_whale:
                n_whales += 1
                # رسالة واضحة و قصيرة
                msg = (
                    f"🐋 *Whale Detected*\n"
                    f"💰 {e['sol']} SOL\n"
                    f"[Solscan](https://solscan.io/tx/{e['sig']})"
                )
                send_tg(msg, disable_preview=False)

            if "MINT" in (e.get("type") or ""):
                n_mints += 1
                mint = e.get("mint") or "unknown"
                msg = (
                    f"⚡ *New Token Minted*\n"
                    f"`{mint}`\n"
                    f"[Solscan](https://solscan.io/token/{mint}) | [DexScreener](https://dexscreener.com/solana/{mint})\n"
                    f"📊 CrypsScore: 4/10"
                )
                send_tg(msg, disable_preview=False)

        except Exception as ex:
            log.error(f"Process tx error: {ex}")

    # لا ترسل أي خلاصة إذا كان 0 0
    append_log(f"Feed: {n_mints} mints, {n_whales} whale txs")
    return jsonify(ok=True, mints=n_mints, whales=n_whales)

# ========= BOOT =========
ensure_files()
log.info("Cryps Ultra Pilot Manual Mode loaded ✅")

if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
