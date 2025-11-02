# app.py — Cryps Ultra Pilot v1.3
from flask import Flask, request, jsonify
import os, json, time, datetime as dt, requests
from typing import Any, Dict, List

app = Flask(__name__)

# ========= ENV =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID   = os.getenv("CHAT_ID", "")
HEL_SECRET = (
    os.getenv("HEL_SECRET")
    or os.getenv("HEL_WEBHOOK_SECRET")
    or "cryps_secret_943k29"
)

# ========= DATA FILES =========
DATA_DIR      = os.getenv("DATA_DIR", "data")
TOKENS_FILE   = os.path.join(DATA_DIR, "tokens.json")   # events cache
SIGNALS_FILE  = os.path.join(DATA_DIR, "signals.log")   # text log
WHALES_FILE   = os.path.join(DATA_DIR, "whales.txt")    # one address per line
RAY_FILE      = os.path.join(DATA_DIR, "raydium_pools.json")  # optional list[]

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)
if not os.path.exists(SIGNALS_FILE):
    open(SIGNALS_FILE, "a", encoding="utf-8").close()
if not os.path.exists(WHALES_FILE):
    open(WHALES_FILE, "a", encoding="utf-8").close()
if not os.path.exists(RAY_FILE):
    with open(RAY_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

# ========= HELPERS =========
def now_ts() -> int:
    return int(time.time())

def send_tg(text: str) -> None:
    """Send message to Telegram if BOT_TOKEN & CHAT_ID are present."""
    if not (BOT_TOKEN and CHAT_ID):
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
            params={"chat_id": CHAT_ID, "text": text, "parse_mode": "Markdown"},
            timeout=8,
        )
    except Exception:
        pass

def log_line(msg: str) -> None:
    try:
        with open(SIGNALS_FILE, "a", encoding="utf-8") as log:
            log.write(f"{dt.datetime.utcnow().isoformat()}Z | {msg}\n")
    except Exception:
        pass

def load_json(path: str, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path: str, data: Any) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

def read_whales() -> List[str]:
    try:
        with open(WHALES_FILE, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []

def write_whales(addrs: List[str]) -> None:
    with open(WHALES_FILE, "w", encoding="utf-8") as f:
        f.write("\n".join(addrs) + ("\n" if addrs else ""))

def add_whale(addr: str) -> bool:
    addr = (addr or "").strip()
    if not addr or len(addr) < 30:
        return False
    whales = read_whales()
    if addr in whales:
        return False
    whales.append(addr)
    write_whales(whales)
    return True

def remove_whale(addr: str) -> bool:
    addr = (addr or "").strip()
    whales = read_whales()
    if addr not in whales:
        return False
    whales = [w for w in whales if w != addr]
    write_whales(whales)
    return True

def ray_accounts_set():
    try:
        arr = load_json(RAY_FILE, [])
        return set(arr if isinstance(arr, list) else [])
    except Exception:
        return set()

# ========= MINI DB / ANALYTICS =========
def upsert_token_event(event: Dict[str, Any]) -> None:
    """Append event; keep last 10k."""
    db = load_json(TOKENS_FILE, [])
    db.append(event)
    if len(db) > 10000:
        db = db[-10000:]
    save_json(TOKENS_FILE, db)

def winners_last_24h(limit: int = 10) -> List[Dict[str, Any]]:
    """Aggregate events in last 24h by mint and rank by SOL sum / count / recency."""
    db = load_json(TOKENS_FILE, [])
    cutoff = now_ts() - 24 * 3600
    agg: Dict[str, Dict[str, Any]] = {}
    for e in db:
        if e.get("ts", 0) < cutoff:
            continue
        mint = e.get("mint") or "Unknown"
        rec = agg.setdefault(
            mint, {"mint": mint, "count": 0, "sol_sum": 0.0, "last_sig": "", "last_ts": 0}
        )
        rec["count"] += 1
        rec["sol_sum"] += float(e.get("sol_value", 0.0) or 0.0)
        if e.get("ts", 0) >= rec["last_ts"]:
            rec["last_sig"] = e.get("signature", "")
            rec["last_ts"] = e.get("ts", 0)
    ranked = sorted(
        agg.values(), key=lambda x: (x["sol_sum"], x["count"], x["last_ts"]), reverse=True
    )
    return ranked[:limit]

# ========= ROUTES =========
@app.get("/")
def home():
    return "Cryps Ultra Pilot v1.3 ✅"

@app.get("/healthz")
def healthz():
    return jsonify(ok=True, ts=now_ts(), whales=len(read_whales()))

# ----- TELEGRAM WEBHOOK -----
@app.post("/tg-webhook")
def tg_webhook():
    """Handle Telegram updates (commands)."""
    data = request.get_json(silent=True) or {}
    msg = ((data.get("message") or {}).get("text") or "").strip()
    low = msg.lower()

    if low in ("/start", "start"):
        send_tg(
            "✅ *Cryps Ultra Pilot Online*\n"
            "Commands: `/scan` | `/winners` | `/kinchi` | `/whales`\n"
            "Admin: `/whale_add <addr>` `/whale_remove <addr>`"
        )
        return jsonify(ok=True)

    if low in ("/scan", "scan"):
        send_tg("🔎 *Cryps Ultra Scanner*\nScanning latest on-chain mints & whales…")
        log_line("TG: /scan")
        return jsonify(ok=True)

    if low in ("/winners", "winners"):
        top = winners_last_24h(10)
        if not top:
            send_tg("🏆 *Top Winner Tokens (24h)*\nNo data yet.")
            return jsonify(ok=True)
        lines = ["🏆 *Top Winner Tokens (24h)*"]
        for i, r in enumerate(top, 1):
            mint, sol, cnt, sig = r["mint"], r["sol_sum"], r["count"], r["last_sig"]
            solscan = f"https://solscan.io/tx/{sig}" if sig else ""
            tokurl = f"https://solscan.io/token/{mint}" if mint != "Unknown" else ""
            lines.append(f"{i}. `{mint}` • {sol:.2f} SOL • {cnt} txs")
            if tokurl:
                lines.append(tokurl)
            if solscan:
                lines.append(solscan)
        send_tg("\n".join(lines))
        log_line("TG: /winners")
        return jsonify(ok=True)

    if low in ("/kinchi", "kinchi"):
        send_tg("📊 *Live Whale Heatmap*\nCollecting signals from Helius…")
        log_line("TG: /kinchi")
        return jsonify(ok=True)

    if low.startswith("/whale_add") or low.startswith("whale_add"):
        parts = msg.split()
        if len(parts) >= 2 and len(parts[1]) >= 30:
            ok = add_whale(parts[1])
            send_tg(f"➕ Added whale: `{parts[1]}`" if ok else f"Already/invalid: `{parts[1]}`")
        else:
            send_tg("Usage: `/whale_add <WALLET_ADDRESS>`")
        return jsonify(ok=True)

    if low.startswith("/whale_remove") or low.startswith("whale_remove"):
        parts = msg.split()
        if len(parts) >= 2:
            ok = remove_whale(parts[1])
            send_tg(f"➖ Removed: `{parts[1]}`" if ok else f"Not found: `{parts[1]}`")
        else:
            send_tg("Usage: `/whale_remove <WALLET_ADDRESS>`")
        return jsonify(ok=True)

    if low in ("/whales", "whales"):
        w = read_whales()
        send_tg("No whales yet." if not w else f"*Whales ({len(w)})*\n" + "\n".join([f"{i+1}. `{a}`" for i,a in enumerate(w[:50])]))
        return jsonify(ok=True)

    # default
    send_tg(f"🤖 Unknown command: `{msg}`")
    return jsonify(ok=True)

# ----- HELIUS WEBHOOK -----
@app.post("/hel-webhook")
def hel_webhook():
    """Receive Enhanced Webhook payloads from Helius."""
    header_secret = request.headers.get("X-Cryps-Secret") or request.headers.get("x-cryps-secret")
    query_secret  = request.args.get("secret")
    if (header_secret or query_secret) != HEL_SECRET:
        log_line(f"[HEL] SECRET MISMATCH: got='{header_secret or query_secret}' expected='{HEL_SECRET}'")
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if evt is None:
        return jsonify(error="no_json"), 400

    # Accept dict({"transactions": [...]}) or list([...])
    if isinstance(evt, dict):
        txs = evt.get("transactions", []) or []
    elif isinstance(evt, list):
        txs = evt
    else:
        txs = []

    whales = set(read_whales())
    rayset  = ray_accounts_set()

    n_mints = n_swaps = n_whales = 0
    for tx in txs:
        try:
            sig   = tx.get("signature") or tx.get("signatureId") or ""
            ttype = (tx.get("type") or "").upper()         # TOKEN_MINT / SWAP / TRANSFER...
            ts    = int(tx.get("timestamp") or now_ts())

            # SOL value
            sol_value = 0.0
            for nt in tx.get("nativeTransfers", []) or []:
                amt = float(nt.get("amount", 0) or 0)
                sol_value += (amt / 1e9) if amt > 1e6 else amt

            # mint if present
            mint = None
            if tx.get("tokenTransfers"):
                mt = [tt.get("mint") for tt in tx["tokenTransfers"] if tt.get("mint")]
                mint = mt[0] if mt else None

            # accounts
            accounts = [a.get("account") for a in tx.get("accounts", []) or [] if a.get("account")]
            is_whale = bool(whales and accounts and any(a in whales for a in accounts))
            is_ray   = bool(rayset and accounts and any(a in rayset for a in accounts))

            # persist minimal event
            kind = "TRANSFER"
            if "MINT" in ttype:
                kind = "MINT"; n_mints += 1
            elif "SWAP" in ttype:
                kind = "SWAP"; n_swaps += 1

            upsert_token_event({
                "type": kind, "mint": mint, "signature": sig,
                "sol_value": sol_value, "ts": ts
            })

            # alerts
            alert_lines = []
            if is_whale:
                n_whales += 1
                alert_lines.append("🦈 *Whale TX*")
            if "MINT" in ttype:
                alert_lines.append("⚡ *New Mint*")
            elif "SWAP" in ttype:
                alert_lines.append("💱 *Swap*")
            elif sol_value >= 2.0:
                alert_lines.append("💸 *Big Transfer*")
            if is_ray:
                alert_lines.append("♻️ Raydium")

            if alert_lines:
                txt = " | ".join(alert_lines) + f"\n🪙 `{mint or 'Unknown'}` • {sol_value:.2f} SOL\n🔗 https://solscan.io/tx/{sig}"
                send_tg(txt)

        except Exception as e:
            log_line(f"[HEL] parse_error: {repr(e)}")

    if n_mints or n_swaps or n_whales:
        send_tg(f"📡 *Helius Feed*\nMints: *{n_mints}* • Swaps: *{n_swaps}* • Whales: *{n_whales}*")

    return jsonify(ok=True, parsed=len(txs), mints=n_mints, swaps=n_swaps, whales=n_whales)

# ========= MAIN =========
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
