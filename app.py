# app.py  — Cryps Ultra Pilot (V2.1 Strict Meme/Stop Patch)
import os, json, re
from collections import deque
from datetime import datetime, timezone
from flask import Flask, request, jsonify
import requests

# ---- Optional dotenv ----
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

app = Flask(__name__)

# =========================
# Config / Env
# =========================
BOT_TOKEN   = os.getenv("BOT_TOKEN", "")
CHAT_ID     = os.getenv("CHAT_ID", "")
TG_SECRET   = os.getenv("TG_SECRET", "")            # Telegram webhook secret (query أو header)
HEL_SECRET  = os.getenv("HEL_WEBHOOK_SECRET", "")   # Helius header X-Cryps-Secret
APP_URL     = os.getenv("APP_URL", "")              # https://<your-render-app>.onrender.com

# =========================
# Runtime State (Commands)
# =========================
LIVE_FEED        = False     # /kinchi → ON
HARD_MUTE        = False     # /stop   → OFF (يصكّت كلشي)
SCORE_MIN        = 8         # /threshold <n>
STRICT_MEME_MODE = True      # /mode strict|normal

# Winners cache (last signals) لعرض Top 10
WINNERS = deque(maxlen=50)

# =========================
# Static helpers
# =========================
SOLSCAN_TKN = "https://solscan.io/token/{}"
SOLSCAN_TX  = "https://solscan.io/tx/{}"
DEX_URL     = "https://dexscreener.com/solana/{}"

# حظر الميمتس ديال الستابل/بلو-تشيب
MINT_BLOCKLIST = {
    "So11111111111111111111111111111111111111112",  # wSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v", # USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB", # USDT
}

# فالوضع الصارم ما نقبلوش غير هاد الأنواع
STRICT_TYPES = {"SWAP", "TOKEN_MINT", "CREATE", "MINT"}

# =========================
# Load whales/programs
# =========================
def load_whales():
    path = "data/whales.txt"
    whales = {}
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                ln = ln.strip()
                if not ln or ln.startswith("#"): 
                    continue
                parts = ln.split()
                addr = parts[0]
                tag  = " ".join(parts[1:]) if len(parts) > 1 else ""
                whales[addr] = tag
    return whales

def load_programs():
    # برامج بحال Raydium/Jupiter …
    path = "data/programs.txt"
    progs = set()
    if os.path.exists(path):
        with open(path, "r", encoding="utf-8", errors="ignore") as f:
            for ln in f:
                a = ln.strip()
                if a and not a.startswith("#"):
                    progs.add(a)
    # fallback مفيد (Raydium/Jup الأساسيين)
    if not progs:
        progs.update({
            "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C", # Raydium CPMM
            "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8", # Raydium AMMv4
            "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK", # Raydium CLMM
            "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj", # Raydium LaunchLab
            # Jupiter الكورن غالبا كيتجاب عبر الوسيط، نخليه detection عبر الويرحلز/tags
        })
    return progs

WHALES  = load_whales()   # {address: "TAG"}
PROGRAMS = load_programs()

def short(x, n=6):
    if not x: return ""
    return x[:n] + "…" + x[-n:]

def tg_send(html_text: str):
    if HARD_MUTE:
        return 0
    if not BOT_TOKEN or not CHAT_ID:
        return 0
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    data = {
        "chat_id": CHAT_ID,
        "text": html_text,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        r = requests.post(url, data=data, timeout=15)
        return 1 if r.ok else 0
    except Exception:
        return 0

# =========================
# Scoring (بسيط وعملي)
# =========================
def score_event(evt, whales_hit):
    # base = 5 + bonus حسب الحيتان/cex/program
    score = 5
    whales_n = len(whales_hit)
    cex_n = sum(1 for _, t in whales_hit if t and (
        "cex" in t.lower() or "bridge" in t.lower() or "hot" in t.lower()
    ))
    if whales_n >= 2:
        score += 2
    if cex_n >= 1:
        score += 2
    # حدث من برامج Raydium؟ +1
    prog = (evt.get("programId") or evt.get("program") or "")
    if prog and prog in PROGRAMS:
        score += 1
    # cap to 10
    return min(score, 10)

def format_signal(evt, score, notes, whales_hit):
    sig = (evt.get("type","") or "TX").upper()
    tx  = evt.get("signature") or evt.get("transaction") or ""
    mint = ""
    if evt.get("tokenTransfers"):
        ms = [t.get("mint") for t in evt["tokenTransfers"] if t.get("mint")]
        mint = ms[0] if ms else ""

    whales_n = len(whales_hit)
    cex_n = sum(1 for _, t in whales_hit if t and ("cex" in t.lower() or "bridge" in t.lower() or "hot" in t.lower()))
    notes_line = "·".join(notes + [f"W{whales_n}", f"CEX{cex_n}"])

    title = f"⚡ <b>{sig}</b>  •  CrypsScore: <b>{score}/10</b>  ({notes_line})"
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

# =========================
# Telegram Bot Webhook
# =========================
@app.route("/tg", methods=["POST", "GET"])
def tg():
    global LIVE_FEED, HARD_MUTE, SCORE_MIN, STRICT_MEME_MODE

    # أمان بسيط
    if TG_SECRET:
        sec = request.headers.get("X-Tg-Secret") or request.args.get("secret")
        if sec != TG_SECRET:
            return jsonify({"ok": False, "err": "forbidden"}), 403

    upd = request.get_json(silent=True) or {}
    msg = ((upd.get("message") or upd.get("edited_message")) or {}).get("text", "")
    if not msg:
        return jsonify({"ok": True})

    parts = msg.strip().split()
    cmd = parts[0].lower()
    args = parts[1:]

    def reply(text):
        tg_send(text)
        return jsonify({"ok": True})

    if cmd == "/start":
        return reply("🤖 Cryps Ultra Pilot جاهز.\n/kinchi ON • /stop OFF • /mode strict|normal • /threshold <n> • /winners")

    if cmd == "/kinchi":
        HARD_MUTE = False
        LIVE_FEED = True
        return reply("📡 Live Whale Heatmap <b>ON</b> (strict mode فعال).")

    if cmd == "/stop":
        LIVE_FEED = False
        HARD_MUTE = True
        return reply("🛑 Alerts <b>OFF</b>. تسدّ كلشي.")

    if cmd == "/threshold":
        if not args:
            return reply(f"🔧 Threshold: <b>{SCORE_MIN}</b>")
        try:
            v = int(args[0])
            SCORE_MIN = max(1, min(10, v))
            return reply(f"✅ Threshold set to <b>{SCORE_MIN}</b>")
        except:
            return reply("Usage: /threshold <1..10>")

    if cmd == "/mode":
        if not args:
            return reply(f"Mode: <b>{'strict' if STRICT_MEME_MODE else 'normal'}</b>")
        STRICT_MEME_MODE = (args[0].lower() == "strict")
        return reply("✅ Mode set to <b>" + ("strict" if STRICT_MEME_MODE else "normal") + "</b>")

    if cmd == "/winners":
        if not WINNERS:
            return reply("🥇 No winners cached yet.")
        out = ["🏆 <b>Top Winners</b>"]
        for i, w in enumerate(list(WINNERS)[:10], 1):
            mint = w.get("mint",""); sig = w.get("signature","")
            score = w.get("score","?"); whales = w.get("whales",0); cex = w.get("cex",0)
            link = SOLSCAN_TKN.format(mint) if mint else SOLSCAN_TX.format(sig)
            label = mint or (sig and short(sig)) or "?"
            out.append(f"{i}. <a href='{link}'>{label}</a> — S:{score}/10 · W:{whales} · CEX:{cex}")
        return reply("\n".join(out))

    # أي أمر آخر
    return reply("ℹ️ Commands: /kinchi • /stop • /mode strict|normal • /threshold N • /winners")

# =========================
# Helius Webhook
# =========================
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    # Secret check
    if HEL_SECRET:
        sec = request.headers.get("X-Cryps-Secret")
        if sec != HEL_SECRET:
            return jsonify({"ok": False, "err": "forbidden"}), 403

    # /stop = يسدّ كلشي
    if HARD_MUTE:
        return jsonify({"ok": True, "sent": 0})

    body = request.get_json(silent=True) or {}
    events = body.get("events") or body.get("type", []) or []
    if isinstance(events, dict):
        events = [events]

    sent = 0
    for evt in events:
        try:
            # 1) فلترة مبدئية
            evt_type = (evt.get("type") or "").upper()

            # بلوك-ليست ديال الستابل/بلو-تشيب
            token_transfers = evt.get("tokenTransfers") or []
            mints_evt = {t.get("mint") for t in token_transfers if t.get("mint")}
            if any(m in MINT_BLOCKLIST for m in mints_evt):
                continue

            # وضع صارم: نخلي غير Swap/Mint/Create
            if STRICT_MEME_MODE and evt_type not in STRICT_TYPES:
                continue

            # 2) اصطياد الحيتان/التاغات من العناوين المشاركة
            whales_hit = []
            addrs = set()
            for key in ("source", "destination", "userAccount", "account", "authority"):
                v = evt.get(key)
                if isinstance(v, str) and len(v) > 30:
                    addrs.add(v)
            # شوف even more: accounts لداخل transaction
            for t in (evt.get("accountData") or []):
                if isinstance(t, dict):
                    for k in ("account", "authority", "owner"):
                        vv = t.get(k)
                        if isinstance(vv, str) and len(vv) > 30:
                            addrs.add(vv)

            for a in list(addrs):
                tag = WHALES.get(a, "")
                if tag:
                    whales_hit.append((a, tag))

            # 3) شروط الميم/لانش
            prog = (evt.get("programId") or evt.get("program") or "")
            in_program = bool(prog and prog in PROGRAMS)
            is_cex = any(("cex" in (t or "").lower() or "bridge" in (t or "").lower() or "hot" in (t or "").lower())
                         for _, t in whales_hit)
            has_2_whales = len(whales_hit) >= 2

            if STRICT_MEME_MODE and not (has_2_whales or is_cex or in_program):
                continue

            # 4) التنقيط واتخاذ القرار
            score = score_event(evt, whales_hit)
            if not LIVE_FEED and score < SCORE_MIN:
                continue

            # 5) تهييء الملاحظات
            notes = []
            if in_program: notes.append("Raydium")
            if is_cex:     notes.append("CEX/Bridge")

            # 6) إرسال
            msg = format_signal(evt, score, notes, whales_hit)
            if msg:
                sent += tg_send(msg)

            # 7) Cache winners
            sig = evt.get("signature") or evt.get("transaction") or ""
            mint = ""
            if token_transfers:
                mm = [t.get("mint") for t in token_transfers if t.get("mint")]
                mint = mm[0] if mm else ""
            WINNERS.appendleft({
                "mint": mint, "signature": sig or "",
                "score": score,
                "whales": len(whales_hit),
                "cex": sum(1 for _, t in whales_hit if t and ("cex" in t.lower() or "bridge" in t.lower() or "hot" in t.lower()))
            })

        except Exception:
            continue

    return jsonify({"ok": True, "sent": sent})

# =========================
# Health
# =========================
@app.route("/")
def root():
    return "Cryps Ultra Pilot V2.1"

@app.route("/health")
def health():
    return jsonify({
        "ok": True,
        "live_feed": LIVE_FEED,
        "hard_mute": HARD_MUTE,
        "score_min": SCORE_MIN,
        "strict": STRICT_MEME_MODE,
        "winners_cached": len(WINNERS),
        "whales_loaded": len(WHALES),
        "programs_loaded": len(PROGRAMS),
    })

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.getenv("PORT", "5000")))
