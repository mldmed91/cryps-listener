# app.py — Cryps Ultra Pilot v1.3
from flask import Flask, request, jsonify
import os, json, time, datetime as dt, requests

app = Flask(__name__)

# ====== ENV ======
BOT  = os.getenv("BOT_TOKEN", "")
CHAT = os.getenv("CHAT_ID", "")
HEL_SEC = (os.getenv("HEL_SECRET") or os.getenv("HEL_WEBHOOK_SECRET") or "cryps_secret_943k29")

# ====== DATA PATHS ======
DATA_DIR = os.getenv("DATA_DIR", "data")
TOKENS_FILE  = os.path.join(DATA_DIR, "tokens.json")
WHALES_FILE  = os.path.join(DATA_DIR, "whales.txt")
SIGNALS_FILE = os.path.join(DATA_DIR, "signals.log")

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "w", encoding="utf-8") as f: json.dump([], f)

# ====== HELPERS ======
def now_ts() -> int: return int(time.time())

def send_tg(text: str) -> None:
    if not (BOT and CHAT): return
    try:
        requests.get(f"https://api.telegram.org/bot{BOT}/sendMessage",
                     params={"chat_id": CHAT, "text": text, "parse_mode":"Markdown"})
    except Exception:
        pass

def log_line(msg: str) -> None:
    try:
        with open(SIGNALS_FILE, "a", encoding="utf-8") as f:
            f.write(f"{dt.datetime.utcnow().isoformat()}Z | {msg}\n")
    except Exception:
        pass

def read_whales():
    try:
        with open(WHALES_FILE, "r", encoding="utf-8") as f:
            return [ln.strip() for ln in f if ln.strip()]
    except Exception:
        return []

def load_tokens():
    try:
        with open(TOKENS_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []

def save_tokens(db):
    try:
        with open(TOKENS_FILE, "w", encoding="utf-8") as f:
            json.dump(db, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ====== Dexscreener enrich (بـ cache صغير) ======
_dex_cache = {}  # {mint: (ts, data)}

def dex_get_by_mint(mint: str):
    if not mint: return {}
    now = time.time()
    if mint in _dex_cache and now - _dex_cache[mint][0] < 60:
        return _dex_cache[mint][1]
    try:
        r = requests.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=6)
        j = r.json()
        pairs = (j.get("pairs") or [])
        if not pairs:
            _dex_cache[mint] = (now, {})
            return {}
        best = max(pairs, key=lambda p: float((p.get("liquidity") or {}).get("usd", 0) or 0))
        out = {
            "price": float((best.get("priceUsd") or 0) or 0),
            "liquidity": int((best.get("liquidity") or {}).get("usd", 0) or 0),
            "fdv": float(best.get("fdv", 0) or 0),
            "marketcap": float(best.get("marketCap", 0) or 0),
            "pairUrl": best.get("url") or "",
            "symbol": best.get("baseToken", {}).get("symbol") or "",
            "name": best.get("baseToken", {}).get("name") or "",
        }
        _dex_cache[mint] = (now, out)
        return out
    except Exception:
        return {}

# ====== ROUTES ======
@app.get("/")
def home(): return "Cryps Ultra Pilot v1.3 ✅"

@app.get("/healthz")
def healthz():
    db = load_tokens()
    return jsonify(ok=True, ts=now_ts(), events=len(db), whales=len(read_whales()))

# ====== TELEGRAM WEBHOOK ======
@app.post("/tg-webhook")
def tg_webhook():
    from pilot.kinchi import kinchi_top
    from pilot.winners import winners_24h
    from pilot.qa import qa_summary

    data = request.get_json(silent=True) or {}
    msg = ((data.get("message") or {}).get("text") or "").strip()
    lower = msg.lower()

    if lower in ("/start", "start"):
        send_tg("✅ *Cryps Ultra Pilot Online*\nCommands: `/kinchi` | `/winners` | `/qa <mint>` | `/whales`\nAdmin: `/whale_add <addr>` `/whale_remove <addr>`")
        return jsonify(ok=True)

    if lower in ("/whales", "whales"):
        whales = read_whales()
        send_tg("No whales yet." if not whales else f"*Whales ({len(whales)})*\n" + "\n".join([f"{i+1}. `{a}`" for i,a in enumerate(whales[:50])]))
        return jsonify(ok=True)

    if lower.startswith("/whale_add") or lower.startswith("whale_add"):
        parts = msg.split()
        if len(parts) >= 2 and len(parts[1]) >= 30:
            w = read_whales()
            addr = parts[1].strip()
            if addr not in w:
                w.append(addr)
                with open(WHALES_FILE, "w", encoding="utf-8") as f: f.write("\n".join(w) + "\n")
                send_tg(f"➕ Added whale: `{addr}`")
            else:
                send_tg(f"Already present: `{addr}`")
        else:
            send_tg("Usage: `/whale_add <WALLET_ADDRESS>`")
        return jsonify(ok=True)

    if lower.startswith("/whale_remove") or lower.startswith("whale_remove"):
        parts = msg.split()
        if len(parts) >= 2:
            w = read_whales()
            addr = parts[1].strip()
            if addr in w:
                w = [x for x in w if x != addr]
                with open(WHALES_FILE, "w", encoding="utf-8") as f: f.write("\n".join(w) + ("\n" if w else ""))
                send_tg(f"➖ Removed: `{addr}`")
            else:
                send_tg(f"Not found: `{addr}`")
        else:
            send_tg("Usage: `/whale_remove <WALLET_ADDRESS>`")
        return jsonify(ok=True)

    if lower in ("/kinchi", "kinchi"):
        arr = kinchi_top(TOKENS_FILE, read_whales(), limit=10)
        if not arr:
            send_tg("📡 *Live Whale Heatmap*\nما كايناش داتا كافية دابا. جرّب Send Test فـ Helius أو تسنى أحداث جديدة.")
            return jsonify(ok=True)

        lines = ["💎 *Top 10 Kinchi Tokens*"]
        for i, t in enumerate(arr, 1):
            mint = t.get("mint") or ""
            meta = dex_get_by_mint(mint)
            price = meta.get("price") or t.get("price", 0)
            liq   = meta.get("liquidity") or t.get("liquidity", 0)
            whales= int(t.get("whales", 0) or 0)
            name  = meta.get("name") or t.get("name") or t.get("symbol") or "?"
            sym   = meta.get("symbol") or t.get("symbol") or "?"

            if liq and liq < 10000:  # فلترة بسيطة
                continue

            lines.append(f"{i}. *{name}* ({sym}) — ${float(price):.8f} | 🐋 {whales} | 💧 {int(liq)}")
            lines.append(f"https://solscan.io/token/{mint}")
            if meta.get("pairUrl"): lines.append(meta["pairUrl"])

        lines.append("\n1️⃣ *Nasi7at Cryps*: خليك مع لي عندهم 💧>25k و 🐋≥3.\n2️⃣ *Nasi7at Pilotos*: دير /qa على اللي عجبك قبل ما تاخد قرار.")
        send_tg("\n".join(lines))
        return jsonify(ok=True)

    if lower in ("/winners", "winners"):
        arr = winners_24h(TOKENS_FILE, read_whales(), limit=10)
        if not arr:
            send_tg("🏆 *Top Winners (24h)*\nما كايناش داتا كافية.")
            return jsonify(ok=True)

        lines = ["🏆 *Top Winners (24h)*"]
        for i, t in enumerate(arr, 1):
            mint = t.get("mint") or ""
            meta = dex_get_by_mint(mint)
            price = meta.get("price") or t.get("price", 0)
            liq   = meta.get("liquidity") or t.get("liquidity", 0)
            vol24 = int(t.get("volume24h", 0) or 0)
            whales= int(t.get("whales", 0) or 0)
            name  = meta.get("name") or t.get("name") or t.get("symbol") or "?"
            lines.append(f"{i}. *{name}* — ${float(price):.8f} | 🐋 {whales} | 💧 {int(liq)} | 📊 Vol24h {vol24}")
            lines.append(f"https://solscan.io/token/{mint}")
            if meta.get("pairUrl"): lines.append(meta["pairUrl"])

        lines.append("\n1️⃣ *Nasi7at Cryps*: اختار اللي باقي ناشط خلال آخر 6 سوايع.\n2️⃣ *Nasi7at Pilotos*: تأكد من LP و الـ holders قبل أي خطوة.")
        send_tg("\n".join(lines))
        return jsonify(ok=True)

    if lower.startswith("/qa "):
        parts = msg.split()
        if len(parts) < 2:
            send_tg("استعمال: `/qa <mint_address>`")
            return jsonify(ok=True)

        mint = parts[1].strip()
        db = load_tokens()
        tok = next((x for x in db if (x.get("mint") or "") == mint), None)

        # إيلا ما لقيتوش فالكاش، حاول نغني بالمرة من Dex
        if not tok:
            meta = dex_get_by_mint(mint)
            if not meta:
                send_tg("🔎 ما لقيتش التوكن فالكاش ولا فـ Dex. جرّب من بعد.")
                return jsonify(ok=True)
            tok = {
                "mint": mint,
                "price": meta.get("price", 0),
                "marketcap": meta.get("marketcap", 0),
                "fdv": meta.get("fdv", 0),
                "supply": 1_000_000_000,  # فرضية: 1B إلا عندك supply حقيقي فالداتا
            }

        from pilot.qa import qa_summary
        dcs, (f1, f2, res), verdict = qa_summary(tok)
        send_tg(f"🔬 *QA* `{mint}`\nDataConsistencyScore: *{dcs:.6f}*\nF1={f1:.2f}\nF2={f2:.2f}\nResult={res:.2f}\nVerdict: *{verdict}*")
        return jsonify(ok=True)

    return jsonify(ok=True)

# ====== HELIUS WEBHOOK ======
@app.post("/hel-webhook")
def hel_webhook():
    header_secret = request.headers.get("X-Cryps-Secret") or request.headers.get("x-cryps-secret")
    query_secret  = request.args.get("secret")
    if (header_secret or query_secret) != HEL_SEC:
        log_line(f"[HEL] SECRET MISMATCH: got='{header_secret or query_secret}' expected='{HEL_SEC}'")
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if evt is None: return jsonify(status="no_json"), 400

    # dict({"transactions":[...]}) أو list([...])
    txs = evt.get("transactions", []) if isinstance(evt, dict) else (evt if isinstance(evt, list) else [])

    db = load_tokens()
    whales = set(read_whales())

    parsed = mints = whales_hits = swaps = 0

    for tx in txs:
        try:
            sig   = tx.get("signature") or tx.get("signatureId") or ""
            ttype = (tx.get("type") or "").upper()
            ts    = int(tx.get("timestamp") or now_ts())
            sol_value = 0.0
            for nt in (tx.get("nativeTransfers") or []):
                amt = float(nt.get("amount", 0) or 0)
                sol_value += (amt/1e9) if amt > 1e6 else amt

            mint = None
            mintsList = []
            if tx.get("tokenTransfers"):
                for tt in tx["tokenTransfers"]:
                    m = tt.get("mint")
                    if m: mintsList.append(m)
                mint = mintsList[0] if mintsList else None

            accounts = [a.get("account") for a in (tx.get("accounts") or []) if a.get("account")]
            whale_hit = any(a in whales for a in accounts)

            row = {
                "signature": sig,
                "timestamp": ts,
                "type": ttype,
                "mint": mint,
                "sol": sol_value,
                # enrich placeholders (كيتعمّرو لاحقاً من Dex أو من مصادر أخرى)
                "price": 0.0,
                "liquidity": 0,
                "volume24h": 0,
                "whales": 1 if whale_hit else 0,
                "confidence": 0,
                "marketcap": 0,
                "fdv": 0,
                "supply": 0,
                "name": None,
                "symbol": None,
            }
            db.append(row)
            parsed += 1
            if "SWAP" in ttype: swaps += 1
            if "MINT" in ttype: mints += 1
            if whale_hit: whales_hits += 1

        except Exception as e:
            log_line(f"[HEL] parse_error: {repr(e)}")

    # قصّ الداتا القديمة باش منطفحوش
    if len(db) > 20000: db = db[-20000:]
    save_tokens(db)

    send_tg(f"📡 *Helius Feed* • parsed={parsed} mints={mints} whales={whales_hits} swaps={swaps}")
    return jsonify(ok=True, parsed=parsed, mints=mints, whales=whales_hits, swaps=swaps)

# ====== MAIN ======
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
