# app.py — Cryps Ultra Pilot v1.1
from flask import Flask, request, jsonify
import os, json, time, datetime as dt, requests
from typing import Any, Dict, List

app = Flask(__name__)

# ====== ENV ======
BOT      = os.getenv("BOT_TOKEN", "")
CHAT     = os.getenv("CHAT_ID", "")
HEL_SEC  = (os.getenv("HEL_SECRET")
           or os.getenv("HEL_WEBHOOK_SECRET")
           or "cryps_secret_943k29")

# ====== DATA PATHS ======
DATA_DIR     = os.getenv("DATA_DIR", "data")
TOKENS_FILE  = os.path.join(DATA_DIR, "tokens.json")
SIGNALS_FILE = os.path.join(DATA_DIR, "signals.log")
WHALES_FILE  = os.path.join(DATA_DIR, "whales.txt")

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f:
        json.dump([], f)

# ====== HELPERS ======
def now_ts() -> int:
    return int(time.time())

def send_tg(text: str) -> None:
    if not (BOT and CHAT): 
        return
    try:
        requests.get(
            f"https://api.telegram.org/bot{BOT}/sendMessage",
            params={"chat_id": CHAT, "text": text, "parse_mode": "Markdown"}
        )
    except Exception:
        pass

def log_line(msg: str) -> None:
    try:
        with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.utcnow().isoformat()}Z | {msg}\n")
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
    if not os.path.exists(WHALES_FILE):
        return []
    try:
        with open(WHALES_FILE, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []

# ====== MINI-INTELLIGENCE ======
def upsert_token_event(event: Dict[str, Any]) -> None:
    """
    event: {
      "type": "MINT" | "SWAP" | "TRANSFER",
      "mint": "So111...." (optional),
      "signature": "...",
      "sol_value": float,
      "ts": int
    }
    """
    db = load_json(TOKENS_FILE, [])
    db.append(event)
    # قصّ لآخر 10k حدث باش يبقى خفيف
    if len(db) > 10000:
        db = db[-10000:]
    save_json(TOKENS_FILE, db)

def winners_last_24h(limit: int = 10) -> List[Dict[str, Any]]:
    db = load_json(TOKENS_FILE, [])
    cutoff = now_ts() - 24*3600
    # نجمع حسب mint (اللي بلا mint نديروها Unknown)
    agg: Dict[str, Dict[str, Any]] = {}
    for e in db:
        if e.get("ts", 0) < cutoff: 
            continue
        mint = e.get("mint") or "Unknown"
        rec = agg.setdefault(mint, {"mint": mint, "count": 0, "sol_sum": 0.0, "last_sig": "", "last_ts": 0})
        rec["count"]  += 1
        rec["sol_sum"] += float(e.get("sol_value", 0.0) or 0.0)
        if e.get("ts", 0) >= rec["last_ts"]:
            rec["last_sig"] = e.get("signature", "")
            rec["last_ts"]  = e.get("ts", 0)

    ranked = sorted(agg.values(), key=lambda x: (x["sol_sum"], x["count"], x["last_ts"]), reverse=True)
    return ranked[:limit]

# ====== ROOTS ======
@app.get("/")
def home():
    return "Cryps Ultra Pilot v1.1 ✅"

@app.get("/healthz")
def healthz():
    return jsonify(ok=True, ts=now_ts(), whales=len(read_whales()))

# ====== TELEGRAM ======
@app.post("/tg-webhook")
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg = ((data.get("message") or {}).get("text") or "").strip()
    lower = msg.lower()

    if lower in ("/start", "start"):
        send_tg("✅ *Cryps Ultra Pilot Online*\nCommands: `/scan` | `/winners` | `/kinchi`")
        return jsonify(ok=True)

    if lower in ("/scan", "scan"):
        send_tg("🔎 *Cryps Ultra Scanner*\nScanning latest on-chain mints & whales…")
        # مجرد إشارة لبدء مسح (التحليل الحقيقي كيجي من /hel-webhook)
        log_line("TG: /scan")
        return jsonify(ok=True)

    if lower in ("/winners", "winners"):
        top = winners_last_24h(10)
        if not top:
            send_tg("🏆 *Top Winner Tokens (24h)*\nNo data yet.")
            return jsonify(ok=True)
        lines = ["🏆 *Top Winner Tokens (24h)*"]
        for i, r in enumerate(top, 1):
            mint = r["mint"]
            sol  = r["sol_sum"]
            cnt  = r["count"]
            sig  = r["last_sig"]
            solscan = f"https://solscan.io/tx/{sig}" if sig else ""
            tokurl  = f"https://solscan.io/token/{mint}" if mint != "Unknown" else ""
            lines.append(f"{i}. `{mint}` • {sol:.2f} SOL • {cnt} txs\n{tokurl or ''}")
            if solscan: 
                lines.append(solscan)
        send_tg("\n".join(lines))
        log_line("TG: /winners")
        return jsonify(ok=True)

    if lower in ("/kinchi", "kinchi"):
        send_tg("📡 *Live Whale Heatmap*\nCollecting signals from Helius…")
        log_line("TG: /kinchi")
        return jsonify(ok=True)

    # fallback: ignore
    return jsonify(ok=True)

# ====== HELIUS WEBHOOK ======
@app.post("/hel-webhook")
def hel_webhook():
    # سرّ عبر Header أو Query
    header_secret = request.headers.get("X-Cryps-Secret") or request.headers.get("X-Cryps-Secret".lower())
    query_secret  = request.args.get("secret")
    if (header_secret or query_secret) != HEL_SEC:
        log_line(f"[HEL] SECRET MISMATCH: got='{header_secret or query_secret}' expected='{HEL_SEC}'")
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if evt is None:
        return jsonify(status="no_json"), 400

    # Helius كترجع مرات dict ومرات list (test/console) — نعالج الجوج
    txs: List[Dict[str, Any]] = []
    if isinstance(evt, dict):
        txs = evt.get("transactions", []) or []
    elif isinstance(evt, list):
        txs = evt
    else:
        txs = []

    whales = set(read_whales())  # اختيارياً تستعملهم فالتصفية
    n_swaps = n_mints = 0

    for tx in txs:
        try:
            sig = tx.get("signature") or tx.get("signatureId") or ""
            ttype = tx.get("type", "").upper()  # CREATE / TOKEN_MINT / SWAP / TRANSFER...
            ts = int(tx.get("timestamp", now_ts()))
            # nativeTransfers: [{amount: lamports}] — نردّها SOL
            sol_value = 0.0
            for nt in tx.get("nativeTransfers", []) or []:
                # بعض payloads فيها amount بالـ lamports، وبعضها بالـ SOL — نتحقق
                amt = nt.get("amount", 0)
                amt = float(amt)
                sol_value += (amt/1e9) if amt > 1e6 else amt

            # token mint if exists
            mint = None
            if tx.get("tokenTransfers"):
                # ناخدو أول mint كمرجع
                mint = (tx["tokenTransfers"][0] or {}).get("mint") or None

            # whale filter (اختياري): إذا بغيت تقيد الأحداث غير من حسابات معيّنة
            if whales:
                accs = [a.get("account") for a in tx.get("accounts", []) or [] if a.get("account")]
                if accs and not any(a in whales for a in accs):
                    # ماشي من whale ديالنا
                    pass

            if "MINT" in ttype:
                n_mints += 1
                upsert_token_event({
                    "type": "MINT", "mint": mint, "signature": sig,
                    "sol_value": sol_value, "ts": ts
                })
            elif "SWAP" in ttype:
                n_swaps += 1
                upsert_token_event({
                    "type": "SWAP", "mint": mint, "signature": sig,
                    "sol_value": sol_value, "ts": ts
                })
            else:
                # نخزّن حتى TRANSFER إذا فيه SOL معتبر (>0.5 SOL مثلاً)
                if sol_value >= 0.5:
                    upsert_token_event({
                        "type": ttype or "TRANSFER",
                        "mint": mint, "signature": sig,
                        "sol_value": sol_value, "ts": ts
                    })

        except Exception as e:
            log_line(f"[HEL] parse_error: {repr(e)}")

    if n_mints or n_swaps:
        send_tg(f"⚡ *Helius Feed*\nMints: *{n_mints}* • Swaps: *{n_swaps}*")

    return jsonify(ok=True, parsed=len(txs), mints=n_mints, swaps=n_swaps)

# ====== MAIN ======
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
