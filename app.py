# app.py  — Cryps Ultra Pilot (V2)
# Flask webhook + Telegram commands + Helius parsing (Solana)

import os, json, time, threading
from collections import deque, defaultdict
from typing import Dict, Any, List, Tuple, Set
from flask import Flask, request, jsonify
import requests

# ---- dotenv (optional) -------------------------------------------------------
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

# ---- Config ------------------------------------------------------------------
BOT_TOKEN      = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID        = os.getenv("CHAT_ID", "").strip()
HEL_SECRET     = os.getenv("HEL_SECRET", "").strip()
PUBLIC_BASE    = os.getenv("PUBLIC_BASE_URL", "").rstrip("/")
WHALES_FILE    = os.getenv("WHALES_FILE", "/opt/render/project/src/data/whales.txt")
PROGRAMS_FILE  = os.getenv("PROGRAMS_FILE", "/opt/render/project/src/data/programs.txt")

# Raydium programs (fallback if programs.txt غير موجود)
DEFAULT_PROGRAMS = {
    # Raydium
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # CPMM
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # AMM v4
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # CLMM
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",  # LaunchLab
}

# Dex/Explorers
SOLSCAN_TX   = "https://solscan.io/tx/{}"
SOLSCAN_TKN  = "https://solscan.io/token/{}"
DEX_URL      = "https://dexscreener.com/solana/{}"

# ---- Runtime state -----------------------------------------------------------
app = Flask(__name__)

LIVE_FEED = False                # كيتفعّل فقط بـ /kinchi
WHALES: Dict[str, str] = {}      # addr -> tag (ممكن فارغ)
PROGRAMS: Set[str] = set()       # Raydium/Jupiter… (للـ filtering)
SEEN_TX: deque = deque(maxlen=5000)
WINNERS: deque = deque(maxlen=50)   # cache ديال أفضل إشارات
LAST_PING = 0

# ---- Helpers -----------------------------------------------------------------
def tg_send(text: str, preview=False):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "parse_mode": "HTML",
        "disable_web_page_preview": (not preview),
    }
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception:
        pass

def read_list_file(path: str) -> List[str]:
    try:
        with open(path, "r", encoding="utf-8") as f:
            rows = [x.strip() for x in f.read().splitlines() if x.strip()]
        return rows
    except Exception:
        return []

def load_whales():
    global WHALES
    new_map: Dict[str, str] = {}
    rows = read_list_file(WHALES_FILE)
    for line in rows:
        parts = line.split()
        addr = parts[0].strip()
        tag  = parts[1].strip() if len(parts) > 1 else ""
        new_map[addr] = tag
    WHALES = new_map

def save_whales():
    try:
        lines = []
        for a, t in WHALES.items():
            lines.append(f"{a} {t}".strip())
        os.makedirs(os.path.dirname(WHALES_FILE), exist_ok=True)
        with open(WHALES_FILE, "w", encoding="utf-8") as f:
            f.write("\n".join(lines) + "\n")
    except Exception:
        pass

def load_programs():
    global PROGRAMS
    rows = read_list_file(PROGRAMS_FILE)
    if rows:
        PROGRAMS = set(rows)
    else:
        PROGRAMS = set(DEFAULT_PROGRAMS)

def short(s: str, n=6) -> str:
    return s if len(s) <= (n*2+3) else f"{s[:n]}…{s[-n:]}"

def now_ms() -> int:
    return int(time.time() * 1000)

# ---- Scoring -----------------------------------------------------------------
def is_pool_init(helius_evt: Dict[str, Any]) -> bool:
    """
    heuristic: نبحث على create/initialize فـ instructions أو logs
    """
    try:
        ins = helius_evt.get("instructions", []) + helius_evt.get("innerInstructions", [])
        for i in ins:
            t = (i.get("parsed", {}) or {}).get("type", "").lower()
            name = (i.get("program", "") or "").lower()
            if "initialize" in t or "create" in t:
                return True
            if "createpool" in t or "init" in name:
                return True
        # fallback: logs
        logs = helius_evt.get("logs", [])
        if any("initialize" in (l or "").lower() for l in logs):
            return True
    except Exception:
        pass
    return False

def collect_accounts(evt: Dict[str, Any]) -> Set[str]:
    s: Set[str] = set()
    # accountKeys
    for k in (evt.get("accountKeys") or []):
        if isinstance(k, dict) and "pubkey" in k:
            s.add(k["pubkey"])
        elif isinstance(k, str):
            s.add(k)
    # tokenTransfers
    for t in (evt.get("tokenTransfers") or []):
        for key in ("fromUserAccount", "toUserAccount", "fromTokenAccount", "toTokenAccount", "mint"):
            v = t.get(key)
            if v: s.add(v)
    # native transfers
    for nt in (evt.get("nativeTransfers") or []):
        for key in ("fromUserAccount", "toUserAccount"):
            v = nt.get(key)
            if v: s.add(v)
    return s

def cryps_score(evt: Dict[str, Any], whales_hit: List[Tuple[str,str]]) -> Tuple[int, List[str]]:
    notes = []
    score = 1  # base

    # برنامج ريديوم/جوبتر؟
    prog = evt.get("programId") or evt.get("program") or ""
    if prog in PROGRAMS:
        score += 2
        notes.append("Prog")

    # حوت حاضر
    if whales_hit:
        score += 5
        notes.append("Whale")
        if len(whales_hit) >= 2:
            score += 2
            notes.append("Whales×2")

        # CEX bonus لو التاغ فيه CEX/Hot
        if any("cex" in (t or "").lower() or "hot" in (t or "").lower() for _, t in whales_hit):
            score += 2
            notes.append("CEX")

    # LP ≈ initialized
    if is_pool_init(evt):
        score += 1
        notes.append("LP?")

    if score > 10: score = 10
    return score, notes

# ---- Winners cache -----------------------------------------------------------
def push_winner(payload: Dict[str, Any]):
    WINNERS.appendleft(payload)

def format_signal(evt: Dict[str, Any], score: int, notes: List[str], whales_hit: List[Tuple[str,str]]) -> str:
    sig = evt.get("type","").upper() or "TX"
    sig = "MINT" if "mint" in sig.lower() else sig
    tx  = evt.get("signature") or evt.get("transaction") or ""
    mint = ""
    if evt.get("tokenTransfers"):
        mints = [t.get("mint") for t in evt["tokenTransfers"] if t.get("mint")]
        mint = mints[0] if mints else ""
    title = f"⚡ <b>{sig}</b>  •  CrypsScore: <b>{score}/10</b>  ({'·'.join(notes)})"
    lines = [title]
    if mint:
        lines.append(f"<code>{mint}</code>")
        lines.append(f"<a href='{SOLSCAN_TKN.format(mint)}'>Solscan</a> | <a href='{DEX_URL.format(mint)}'>DexScreener</a>")
    if tx:
        lines.append(f"<a href='{SOLSCAN_TX.format(tx)}'>Tx</a>")
    if whales_hit:
        hh = ", ".join([f"{short(a)}{('['+t+']') if t else ''}" for a,t in whales_hit[:6]])
        lines.append(f"🐋 <b>Whales:</b> {hh}")
    return "\n".join(lines)

# ---- Telegram Bot Commands ---------------------------------------------------
def tg_api(method: str, data: Dict[str, Any]) -> Dict[str, Any]:
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/{method}"
    try:
        r = requests.post(url, json=data, timeout=15)
        return r.json()
    except Exception:
        return {}

def handle_command(cmd: str, args: List[str]) -> str:
    global LIVE_FEED
    cmd = cmd.lower()

    if cmd == "/start":
        return (
            "✅ <b>Cryps Ultra Pilot Online</b>\n"
            "Commands:\n"
            "/kinchi – start live alerts\n"
            "/stop – stop alerts\n"
            "/winners – top tokens (cache)\n"
            "/whales – list\n"
            "/whale_add <addr> [tag]\n"
            "/whale_remove <addr>\n"
            "/qa <mint>\n"
        )

    if cmd == "/kinchi":
        LIVE_FEED = True
        return "📡 Live Whale Heatmap <b>ON</b> — ghadi nsifto ghi fash y9a3 signal."

    if cmd == "/stop":
        LIVE_FEED = False
        return "🛑 Live alerts <b>stopped</b>."

    if cmd == "/winners":
        if not WINNERS:
            return "🥇 No winners cached yet."
        out = ["🏆 <b>Top Winner Tokens</b> (cached):"]
        for i, w in enumerate(list(WINNERS)[:10], 1):
            out.append(f"{i}. {w.get('mint','') or w.get('signature','') } — Score {w.get('score','?')}/10")
        return "\n".join(out)

    if cmd == "/whales":
        if not WHALES:
            return "No whales yet. Add with /whale_add <addr> [tag]."
        rows = []
        for a, t in list(WHALES.items())[:60]:
            rows.append(f"• <code>{a}</code> {t}")
        return "🐋 <b>Whales List:</b>\n" + "\n".join(rows)

    if cmd == "/whale_add":
        if not args:
            return "Usage: /whale_add <addr> [tag]"
        addr = args[0]
        tag  = " ".join(args[1:]) if len(args) > 1 else ""
        WHALES[addr] = tag
        save_whales()
        return f"✅ Added whale: <code>{addr}</code> {tag}"

    if cmd == "/whale_remove":
        if not args:
            return "Usage: /whale_remove <addr>"
        addr = args[0]
        if addr in WHALES:
            WHALES.pop(addr, None)
            save_whales()
            return f"🗑 Removed: <code>{addr}</code>"
        return "Address not found."

    if cmd == "/qa":
        if not args:
            return "Usage: /qa <mint>"
        m = args[0]
        link = f"<a href='{SOLSCAN_TKN.format(m)}'>Solscan</a> | <a href='{DEX_URL.format(m)}'>DexScreener</a>"
        return f"🧪 Quick QA for:\n<code>{m}</code>\n{link}"

    return "Unknown command."

@app.route("/bot", methods=["POST"])
def bot_webhook():
    """
    Telegram webhook (اختياري). إلا ما درتوهاش، استعمل getUpdates باش تجرب لوكالياً.
    """
    data = request.get_json(silent=True) or {}
    msg  = (data.get("message") or data.get("edited_message")) or {}
    text = (msg.get("text") or "").strip()
    if not text:
        return jsonify(ok=True)

    parts = text.split()
    cmd, args = parts[0], parts[1:]
    resp = handle_command(cmd, args)
    if resp:
        tg_send(resp)
    return jsonify(ok=True)

# ---- Helius Webhook ----------------------------------------------------------
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    # Authentication header
    secret = request.args.get("secret") or request.headers.get("X-Cryps-Secret")
    if HEL_SECRET and secret != HEL_SECRET:
        return jsonify({"ok": False, "error": "forbidden"}), 403

    payload = request.get_json(silent=True) or {}
    events = payload if isinstance(payload, list) else payload.get("events") or payload.get("data") or []
    if not events:
        return jsonify({"ok": True, "n": 0})

    load_whales()     # hot-reload lists
    load_programs()

    sent = 0
    for evt in events:
        # Filter program
        prog = evt.get("programId") or evt.get("program") or ""
        if prog and PROGRAMS and prog not in PROGRAMS:
            continue

        sig = evt.get("signature") or evt.get("transaction")
        if sig and sig in SEEN_TX:
            continue

        accs = collect_accounts(evt)
        whales_hit = [(a, WHALES.get(a, "")) for a in accs if a in WHALES]
        if not whales_hit:
            # ما كنبغيوش الضوضاء — إلا كان LIVE OFF أو بلا حوت، ما كنسيفطوش
            if not LIVE_FEED:
                continue

        score, notes = cryps_score(evt, whales_hit)
        if score < 4 and not LIVE_FEED:
            continue

        # build mint/tx for cache
        mint = ""
        if evt.get("tokenTransfers"):
            ms = [t.get("mint") for t in evt["tokenTransfers"] if t.get("mint")]
            mint = ms[0] if ms else ""

        # winners criteria
        if score >= 8 and (mint or sig):
            push_winner({"mint": mint, "signature": sig, "score": score})

        # send
        if LIVE_FEED or score >= 8:
            text = format_signal(evt, score, notes, whales_hit)
            tg_send(text, preview=True)
            sent += 1

        if sig:
            SEEN_TX.append(sig)

    return jsonify({"ok": True, "sent": sent})

# ---- Health / Root -----------------------------------------------------------
@app.route("/")
def root():
    return jsonify({
        "name": "Cryps Ultra Pilot V2",
        "live": LIVE_FEED,
        "whales": len(WHALES),
        "programs": len(PROGRAMS),
        "winners_cached": len(WINNERS),
        "public_base_url": PUBLIC_BASE or "",
        "webhook": (PUBLIC_BASE + "/hel-webhook?secret="+HEL_SECRET) if (PUBLIC_BASE and HEL_SECRET) else None
    })

# ---- Startup -----------------------------------------------------------------
def boot_msg():
    load_whales()
    load_programs()
    tg_send("✅ Cryps Ultra Pilot V2 is live.\nUse /kinchi to start alerts.\nUse /winners to see cached tops.")

if __name__ == "__main__":
    boot_msg()
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "10000")))
