# app.py — Cryps Ultra Pilot (Final, no external deps)
import os, json, time, threading, traceback
from datetime import datetime
from urllib.parse import urlencode
from urllib.request import urlopen, Request

from flask import Flask, request, jsonify

app = Flask(__name__)

# ========= ENV =========
BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID     = os.getenv("CHAT_ID", "").strip()
HEL_SECRET  = (os.getenv("HEL_SECRET") or os.getenv("HEL_WEBHOOK_SECRET") or "cryps_secret_943k29").strip()

DATA_DIR        = os.getenv("DATA_DIR", "data")
TOKENS_PATH     = os.path.join(DATA_DIR, "tokens.json")
WHALES_PATH     = os.path.join(DATA_DIR, "whales.txt")
SIGNALS_LOG     = os.path.join(DATA_DIR, "signals.log")

os.makedirs(DATA_DIR, exist_ok=True)
if not os.path.exists(TOKENS_PATH):
    with open(TOKENS_PATH, "w", encoding="utf-8") as f:
        json.dump({"events":[]}, f)

if not os.path.exists(WHALES_PATH):
    with open(WHALES_PATH, "w", encoding="utf-8") as f:
        f.write("# put whale addresses here, one per line\n")

# ========= GLOBAL STATE =========
_NOTIFY_LIVE = False              # /kinchi ON -> True ; /stop -> False
_LAST_ALERT  = {}                 # anti-spam per mint/signature
_SPAM_COOLDOWN = 90               # seconds
_WHALES_CACHE = set()
_WHALES_MTIME = 0
_WHALES_LOCK  = threading.Lock()

# Important program accounts (Raydium/Jupiter/Phantom/Relay/OKX Router…)
IMPORTANT_PROGRAMS = {
    # Raydium Mainnet programs
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # CPMM
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # v4 AMM
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # CLMM
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",  # LaunchLab
    # Jupiter misc (limit/referral vaults often present near swaps)
    "j1oeQoPeuEDmjvyMwBmCWexzCQup77kbKKxV59CnYbd",
    "j1opmdubY84LUeidrPCsSGskTCYmeJVzds1UWm6nngb",
    "j1oxqtEHFn7rUkdABJLmtVtz5fFmHFs4tCG3fWJnkHX",
    "j1oAbxxiDUWvoHxEDhWE7THLjEkDQW2cSHYn2vttxTF",
    # Relay/OKX router often used in routes
    "F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe",  # relay.link solver
    "HV1KXxWFaSeriyFvXyx48FqG9BoFbfinB8njCJonqP7K",  # OKX router authority
}

# ========= UTILS =========
def now_ts() -> int:
    return int(time.time())

def iso() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"

def log_line(msg: str) -> None:
    try:
        with open(SIGNALS_LOG, "a", encoding="utf-8") as f:
            f.write(f"{iso()} | {msg}\n")
    except Exception:
        pass

def send_tg(text: str) -> None:
    """Use Telegram Bot API without external deps."""
    if not (BOT_TOKEN and CHAT_ID): 
        return
    try:
        params = {
            "chat_id": CHAT_ID,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True
        }
        url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage?" + urlencode(params)
        with urlopen(url, timeout=10) as _:
            pass
    except Exception as e:
        log_line(f"[TG_ERR] {repr(e)}")

def load_json(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def save_json(path, data) -> None:
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception:
        pass

# ========= WHALES WATCHER =========
def _reload_whales(force=False):
    global _WHALES_CACHE, _WHALES_MTIME
    try:
        m = os.path.getmtime(WHALES_PATH)
    except FileNotFoundError:
        return
    if force or m != _WHALES_MTIME:
        with _WHALES_LOCK:
            try:
                with open(WHALES_PATH, "r", encoding="utf-8") as f:
                    lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
                # address is first token per line
                _WHALES_CACHE = {ln.split()[0] for ln in lines}
                _WHALES_MTIME = m
                log_line(f"[WHALES] loaded={len(_WHALES_CACHE)}")
            except Exception as e:
                log_line(f"[WHALES_ERR] {repr(e)}")

def whales_set():
    # quick copy
    with _WHALES_LOCK:
        return set(_WHALES_CACHE)

def start_whales_watcher(interval=15):
    def watch():
        while True:
            _reload_whales()
            time.sleep(interval)
    threading.Thread(target=watch, daemon=True).start()

def add_whale(addr: str, tag: str = "") -> bool:
    addr = (addr or "").strip()
    if len(addr) < 30:
        return False
    try:
        lines = []
        if os.path.exists(WHALES_PATH):
            with open(WHALES_PATH, "r", encoding="utf-8") as f:
                lines = f.read().splitlines()
        exists = any((ln.strip().split()[0] == addr) for ln in lines if ln.strip() and not ln.strip().startswith("#"))
        if exists:
            return False
        lines.append(f"{addr} {tag}".rstrip())
        with open(WHALES_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(lines).strip() + "\n")
        _reload_whales(force=True)
        return True
    except Exception:
        return False

def remove_whale(addr: str) -> bool:
    addr = (addr or "").strip()
    try:
        if not os.path.exists(WHALES_PATH):
            return False
        with open(WHALES_PATH, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()
        new_lines = []
        removed = False
        for ln in lines:
            if ln.strip() and not ln.strip().startswith("#"):
                if ln.split()[0] == addr:
                    removed = True
                    continue
            new_lines.append(ln)
        with open(WHALES_PATH, "w", encoding="utf-8") as f:
            f.write("\n".join(new_lines).strip() + ("\n" if new_lines else ""))
        _reload_whales(force=True)
        return removed
    except Exception:
        return False

# ========= DATA STORE =========
def append_event(ev: dict) -> None:
    db = load_json(TOKENS_PATH, {"events":[]})
    db["events"].append(ev)
    # keep last N
    db["events"] = db["events"][-6000:]
    save_json(TOKENS_PATH, db)

def events_db():
    return load_json(TOKENS_PATH, {"events":[]})

# ========= CORE PARSING =========
def parse_helius_tx(tx: dict) -> dict:
    """
    Normalize Helius txn to minimal event shape.
    """
    sig   = tx.get("signature") or tx.get("signatureId") or ""
    ttype = (tx.get("type") or "").upper()
    ts    = int(tx.get("timestamp") or now_ts())

    # SOL value
    sol_value = 0.0
    for nt in tx.get("nativeTransfers", []) or []:
        amt = nt.get("amount", 0) or 0
        # Helius native amount is lamports sometimes; normalize if too big
        if amt > 1e6:
            sol_value += float(amt) / 1e9
        else:
            sol_value += float(amt)

    # Mint (first tokenTransfer mint if any)
    mint = None
    if tx.get("tokenTransfers"):
        for t in tx["tokenTransfers"]:
            if t and t.get("mint"):
                mint = t.get("mint")
                break

    # Accounts touched
    accounts = []
    for a in tx.get("accounts", []) or []:
        acc = a.get("account")
        if acc:
            accounts.append(acc)

    # important program touch?
    touched_program = any(acc in IMPORTANT_PROGRAMS for acc in accounts)

    return {
        "sig": sig,
        "type": ttype,
        "ts": ts,
        "sol": round(sol_value, 6),
        "mint": mint,
        "accounts": accounts,
        "prog_touch": touched_program,
    }

def whale_hits(accounts: list) -> (int, list):
    ws = whales_set()
    hits = [a for a in (accounts or []) if a in ws]
    return len(hits), hits

def should_alert(key: str, cooldown=_SPAM_COOLDOWN) -> bool:
    t = now_ts()
    last = _LAST_ALERT.get(key, 0)
    if t - last >= cooldown:
        _LAST_ALERT[key] = t
        return True
    return False

# ========= SCORING (CrypsScore V2) =========
def winners_last_24h(limit=10):
    db = events_db()
    evs = db.get("events", [])
    if not evs:
        return []

    now = now_ts()
    cutoff_24h = now - 24*3600
    cutoff_1h  = now - 3600

    # Aggregate by mint
    agg = {}
    for e in evs:
        if e.get("ts", 0) < cutoff_24h:
            continue
        mint = e.get("mint")
        if not mint:
            continue
        rec = agg.setdefault(mint, {
            "mint": mint,
            "evs": 0,
            "sol_24h": 0.0,
            "last_ts": 0,
            "acc_set": set(),
            "whale_1h": 0,
            "whale_24h": 0,
            "prog_touches": 0
        })
        rec["evs"] += 1
        rec["sol_24h"] += float(e.get("sol") or 0.0)
        rec["last_ts"] = max(rec["last_ts"], e.get("ts", 0))
        rec["acc_set"].update(e.get("accounts", []))
        if e.get("prog_touch"):
            rec["prog_touches"] += 1
        # whale counters (we stored in event)
        if e.get("whale_hits", 0) > 0:
            rec["whale_24h"] += 1
            if e["ts"] >= cutoff_1h:
                rec["whale_1h"] += 1

    # Score
    scored = []
    for mint, r in agg.items():
        age_min = max(1.0, (now - r["last_ts"]) / 60.0)
        fresh = 1.0 / (1.0 + (age_min**0.25))  # softer decay
        diversity = min(1.0, len(r["acc_set"]) / 15.0)

        # Heuristic weighting
        whaleScore = r["whale_1h"]*3 + r["whale_24h"]*1.5
        flowScore  = r["sol_24h"] / 10.0
        metaScore  = r["evs"]*0.4 + r["prog_touches"]*1.2 + diversity*2.0
        total = round( (whaleScore*0.55 + flowScore*0.15 + metaScore*0.15 + fresh*3.0), 1)

        scored.append({
            "mint": mint,
            "score": total,
            "whale_1h": r["whale_1h"],
            "whale_24h": r["whale_24h"],
            "sol_24h": round(r["sol_24h"], 2),
            "evs": r["evs"],
            "fresh": round(fresh, 2),
            "diversity": round(diversity, 2),
            "last_ts": r["last_ts"],
        })

    scored.sort(key=lambda x: (x["score"], x["last_ts"]), reverse=True)
    return scored[:limit]

# ========= ROUTES =========
@app.get("/")
def home():
    return "Cryps Ultra Pilot ✅"

@app.get("/healthz")
def healthz():
    return jsonify(
        ok=True,
        ts=now_ts(),
        whales=len(whales_set()),
        live=_NOTIFY_LIVE,
        events=len(events_db().get("events", []))
    )

# --- Telegram webhook ---
@app.post("/tg-webhook")
def tg_webhook():
    global _NOTIFY_LIVE
    data = request.get_json(silent=True) or {}
    msg = ((data.get("message") or {}).get("text") or "").strip()
    lower = msg.lower()

    if lower in ("/start", "start"):
        send_tg("✅ *Cryps Ultra Pilot Online*\nCommands:\n`/kinchi` (start live alerts)\n`/stop` (stop alerts)\n`/winners` (top tokens 24h)\n`/whales` (list)\n`/whale_add <addr> [tag]`\n`/whale_remove <addr>`\n`/qa <mint>` (quick info)")
        return jsonify(ok=True)

    if lower in ("/kinchi", "kinchi"):
        _NOTIFY_LIVE = True
        send_tg("📡 *Live Whale Heatmap ON* — ghadi nsifto ghi fash yوقع signal.")
        return jsonify(ok=True)

    if lower in ("/stop", "stop"):
        _NOTIFY_LIVE = False
        send_tg("🛑 Live alerts stopped.")
        return jsonify(ok=True)

    if lower.startswith("/whale_add") or lower.startswith("whale_add"):
        parts = msg.split()
        if len(parts) >= 2:
            addr = parts[1]
            tag  = " ".join(parts[2:]) if len(parts) > 2 else ""
            ok = add_whale(addr, tag)
            send_tg(("➕ Added whale: `" + addr + "`") if ok else ("Already/invalid: `" + addr + "`"))
        else:
            send_tg("Usage: `/whale_add <address> [tag]`")
        return jsonify(ok=True)

    if lower.startswith("/whale_remove") or lower.startswith("whale_remove"):
        parts = msg.split()
        if len(parts) >= 2:
            ok = remove_whale(parts[1])
            send_tg(("➖ Removed: `" + parts[1] + "`") if ok else ("Not found: `" + parts[1] + "`"))
        else:
            send_tg("Usage: `/whale_remove <address>`")
        return jsonify(ok=True)

    if lower in ("/whales", "whales"):
        ws = sorted(list(whales_set()))
        if not ws:
            send_tg("No whales yet. Add with `/whale_add <addr> [tag]`.")
        else:
            preview = "\n".join([f"{i+1}. `{a}`" for i,a in enumerate(ws[:50])])
            send_tg(f"*Whales ({len(ws)})*\n{preview}")
        return jsonify(ok=True)

    if lower in ("/winners", "winners"):
        top = winners_last_24h(10)
        if not top:
            send_tg("🏆 *Top Winner Tokens (24h)*\nNo data yet.")
            return jsonify(ok=True)
        lines = ["🏆 *Top Winner Tokens (24h)*"]
        for i, r in enumerate(top, 1):
            mint = r["mint"]; score = r["score"]
            lines.append(f"{i}. `{mint}` • CrypsScore: *{score}*/10 • 🦈1h: {r['whale_1h']} • 💧SOL24h: {r['sol_24h']}")
            lines.append(f"https://solscan.io/token/{mint}")
        send_tg("\n".join(lines))
        return jsonify(ok=True)

    if lower.startswith("/qa "):
        parts = msg.split()
        if len(parts) >= 2:
            mint = parts[1]
            # simple lookup in recent events
            db = events_db().get("events", [])
            last_sig = ""
            sol24 = 0.0; whale1h=whale24h=0; last_ts=0; evs=0
            now = now_ts()
            cutoff24 = now - 24*3600
            cutoff1h = now - 3600
            for e in db:
                if e.get("mint") != mint: 
                    continue
                if e.get("ts",0) >= cutoff24:
                    evs += 1
                    sol24 += float(e.get("sol") or 0.0)
                    last_ts = max(last_ts, e.get("ts", 0))
                    if e.get("whale_hits",0) > 0:
                        whale24h += 1
                        if e["ts"] >= cutoff1h:
                            whale1h += 1
                    if e.get("sig"): last_sig = e["sig"]
            score = winners_last_24h(50)
            score_item = next((x for x in score if x["mint"] == mint), None)
            sc = score_item["score"] if score_item else 0
            lines = [
                f"*QA — `{mint}`*",
                f"CrypsScore: *{sc}*/10",
                f"🦈 Whale(1h/24h): {whale1h}/{whale24h}",
                f"💧 SOL(24h): {round(sol24,2)} | 📚 evs: {evs}",
                f"🔗 Token: https://solscan.io/token/{mint}"
            ]
            if last_sig:
                lines.append(f"🔗 Last TX: https://solscan.io/tx/{last_sig}")
            send_tg("\n".join(lines))
        else:
            send_tg("Usage: `/qa <mint>`")
        return jsonify(ok=True)

    # ignore other messages quietly
    return jsonify(ok=True)

# --- Helius webhook ---
@app.post("/hel-webhook")
def hel_webhook():
    # Auth
    header_secret = request.headers.get("X-Cryps-Secret") or request.headers.get("x-cryps-secret")
    query_secret  = request.args.get("secret")
    if (header_secret or query_secret) != HEL_SECRET:
        log_line(f"[HEL] SECRET MISMATCH: got='{header_secret or query_secret}' expected='{HEL_SECRET}'")
        return jsonify(error="unauthorized"), 403

    evt = request.get_json(silent=True)
    if evt is None:
        return jsonify(status="no_json"), 400

    if isinstance(evt, dict):
        txs = evt.get("transactions", []) or []
    elif isinstance(evt, list):
        txs = evt
    else:
        txs = []

    parsed = 0
    n_mints = n_swaps = n_whales = 0

    for raw in txs:
        try:
            e = parse_helius_tx(raw)
            if not e.get("sig"):
                continue

            # whale detection
            hits, touched = whale_hits(e.get("accounts", []))
            if hits > 0:
                e["whale_hits"] = hits
                e["whales"] = touched
                n_whales += 1
            else:
                e["whale_hits"] = 0

            # normalize type for counters
            ttype = e["type"]
            if "MINT" in ttype:
                n_mints += 1
            elif "SWAP" in ttype:
                n_swaps += 1

            # persist
            append_event(e)
            parsed += 1

            # live alert (only if /kinchi enabled)
            if _NOTIFY_LIVE and e["whale_hits"] > 0:
                key = f"mint:{e.get('mint') or 'Unknown'}"
                if should_alert(key):
                    mint = e.get("mint") or "Unknown"
                    txu  = f"https://solscan.io/tx/{e['sig']}"
                    lines = [
                        "🐋 *Whale TX detected*",
                        f"🪙 `{mint}` • 💧{e['sol']} SOL • 🧭 {e['type']}",
                        f"🔗 {txu}"
                    ]
                    send_tg("\n".join(lines))

        except Exception as ex:
            log_line(f"[HEL_PARSE_ERR] {repr(ex)}\n{traceback.format_exc()}")

    # summary ping (lightweight, no spam)
    if _NOTIFY_LIVE and (n_mints or n_swaps or n_whales) and should_alert("feed:summary", cooldown=60):
        send_tg(f"📡 *Helius Feed*\nMints: *{n_mints}* • Swaps: *{n_swaps}* • Whales: *{n_whales}*")

    return jsonify(ok=True, parsed=parsed, mints=n_mints, swaps=n_swaps, whales=n_whales)

# ========= MAIN =========
if __name__ == "__main__":
    _reload_whales(force=True)
    start_whales_watcher(15)
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
