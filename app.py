# app.py
import os, json, time, threading
from datetime import datetime, timedelta, timezone
from collections import defaultdict
from flask import Flask, request, jsonify
import requests

# =========[ ENV / CONFIG ]=========
from dotenv import load_dotenv
load_dotenv()

BOT_TOKEN   = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID     = os.getenv("CHAT_ID", "").strip()
TG_SECRET   = os.getenv("TG_SECRET", "tgsecret").strip()
HEL_SECRET  = os.getenv("HEL_SECRET", "helsecret").strip()

DATA_DIR = "data"
os.makedirs(DATA_DIR, exist_ok=True)

WHALES_FILE = os.path.join(DATA_DIR, "whales.txt")  # لائحة العناوين (Whales/CEX/MEV…)
STATE_FILE  = os.path.join(DATA_DIR, "state.json")  # حالة التشغيل و الإعدادات
CLUSTERS_DB = os.path.join(DATA_DIR, "clusters.json")  # تخزين التجميعات حسب mint
LOG_FILE    = os.path.join(DATA_DIR, "signals.log")  # لوج للإشارات اللي تبعات

# =========[ GLOBAL STATE ]=========
app = Flask(__name__)
lock = threading.Lock()

# حالة التشغيل: كيشتغل غير ملي تعطي /start فتيليجرام أو /control
DEFAULT_STATE = {
    "RUNNING": False,             # مايصايفط حتى تعطي الأمر
    "COOLDOWN_SEC": 90,           # كولداون بين الرسايل فـ TG
    "TOP_N": 10,                  # عدد ال Winners ف /winners
    "MIN_SCORE": 70,              # حد أدنى للسكور باش يدوز
    "WINDOW_MIN": 120,            # نافذة التحليل بالدقايق (آخر 120 دقيقة)
    "ALLOW_AUTO_PUSH": False      # وخا RUNNING True، بقا معطّل Auto Push (تحكّم يدوي)
}

BASE_FILTER = {
    # فلترة التوكنات الكلاسيكية باش مانخسروش الكريدي على SOL/USDC/USDT…
    "block_mints": set([
        "So11111111111111111111111111111111111111112",  # SOL
        "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",  # USDC
        "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",  # USDT
        # زيد اللي بغيت بسهولة
    ])
}

# برامج Raydium (باش نعرف LP/Initialize)
RAYDIUM_PROGRAMS = set([
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # CPMM
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # AMM v4
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # CLMM
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",  # LaunchLab
])

# =========[ HELPERS ]=========
def _now():
    return datetime.now(timezone.utc)

def load_state():
    if not os.path.exists(STATE_FILE):
        save_state(DEFAULT_STATE)
        return DEFAULT_STATE.copy()
    with open(STATE_FILE, "r") as f:
        try:
            data = json.load(f)
        except:
            data = {}
    # merge defaults for any missing keys
    final = DEFAULT_STATE.copy()
    final.update(data)
    return final

def save_state(st):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=2)

def load_whales():
    # كيقرأ جميع العناوين من whales.txt (كل سطر عنوان)
    if not os.path.exists(WHALES_FILE):
        with open(WHALES_FILE, "w") as f:
            f.write("")
        return set()
    items = set()
    with open(WHALES_FILE, "r") as f:
        for line in f:
            a = line.strip()
            if len(a) > 30:
                items.add(a)
    return items

def load_clusters():
    if not os.path.exists(CLUSTERS_DB):
        with open(CLUSTERS_DB, "w") as f:
            json.dump({}, f)
        return {}
    with open(CLUSTERS_DB, "r") as f:
        try:
            db = json.load(f)
        except:
            db = {}
    return db

def save_clusters(db):
    with open(CLUSTERS_DB, "w") as f:
        json.dump(db, f, indent=2)

def log_line(line):
    with open(LOG_FILE, "a") as log:
        log.write(f"{_now().isoformat()}  {line}\n")

def tg_send(text, disable_preview=True):
    if not BOT_TOKEN or not CHAT_ID:
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text,
        "disable_web_page_preview": disable_preview,
        "parse_mode": "Markdown"
    }
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception as e:
        log_line(f"[TG_ERR] {e}")

def is_noise_mint(mint):
    return mint in BASE_FILTER["block_mints"]

def short(addr):
    if len(addr) < 8: return addr
    return f"{addr[:6]}…{addr[-4:]}"

# =========[ SCORING ]=========
def score_entry(e):
    """
    e: {
      "mint": str,
      "first_seen": iso,
      "last_seen": iso,
      "counts": {"whale":int, "cex":int, "mev":int, "bridges":int},
      "lp_init": bool
    }
    """
    c = e.get("counts", {})
    w = c.get("whale", 0)
    cx = c.get("cex", 0)
    mv = c.get("mev", 0)
    br = c.get("bridges", 0)
    lp = 1 if e.get("lp_init") else 0

    # وزن مخصص للميمات القابلة للانفجار قبل ما تطلع بزاف
    # (Whales + MEV + Bridges قبل LP) = أقوى سيگنال
    base = (w * 12) + (mv * 10) + (br * 14) + (cx * 6) + (lp * 8)

    # decay بسيط مع الوقت: إشارات قديمة تنقص قيمتها
    try:
        last = datetime.fromisoformat(e["last_seen"])
    except:
        last = _now()
    age_min = max(0, (_now() - last).total_seconds() / 60.0)
    decay = max(0.6, 1.0 - (age_min / 240.0))  # ينقص تدريجياً حتى 0.6 خلال ~4 ساعات

    score = int(min(100, base * decay))
    return score

# =========[ CLUSTER LOGIC ]=========
def _ensure_entry(db, mint):
    if mint not in db:
        db[mint] = {
            "mint": mint,
            "first_seen": _now().isoformat(),
            "last_seen": _now().isoformat(),
            "counts": {"whale": 0, "cex": 0, "mev": 0, "bridges": 0},
            "lp_init": False,
            "touchers": set(),  # سنحوّلها ل list عند الحفظ
        }
    return db[mint]

def _classify_addr(addr, whales_set):
    # التصنيف غادي يكون بسيط: بما أن whales.txt فيه خليط (CEX/MEV/Whales/Bridges)
    # نسمّيه "whale" by default، ونديرو تمييز سطحي حسب patterns:
    a = addr
    # لو بغيت تزيد قواعد: prefix/labels… من Arkham/نيمّنغ
    if a in whales_set:
        # مؤشرات بسيطة:
        if a.lower().startswith(("a77h","ast","u6pj","5tzfk","43db")):
            return "cex"
        return "whale"
    return "other"

def _maybe_bridge_label(addr):
    # تقديرية: بعض العناوين ديال bridge اللي نعرفوها (مثال deBridge…)
    # زيد عليهم اللي عندك مع الوقت
    known_bridges = [
        "2snHHreXbpJ7UwZxPe37gnUNf7Wx7wv6UKDSR2JckKuS",  # deBridge
    ]
    return addr in known_bridges

def register_event(db, mint, touch_addrs, ray_prog_hit=False):
    e = _ensure_entry(db, mint)
    e["last_seen"] = _now().isoformat()
    whales = load_whales()

    # صنّف اللمسات:
    w,cx,mv,br = 0,0,0,0
    for a in touch_addrs:
        t = _classify_addr(a, whales)
        if t == "whale": w += 1
        if t == "cex":   cx += 1
        # MEV: تقدير — ممكن تدير لائحة MEV منفصلة وتفرّق بوضوح
        if a in whales and a.lower() not in ("a77h","ast","u6pj","5tzfk","43db"):
            # نعتبر اللي ماطلعش CEX غالباً MEV/Smart
            mv += 1
        if _maybe_bridge_label(a): br += 1

        e["touchers"].add(a)

    e["counts"]["whale"]  += w
    e["counts"]["cex"]    += cx
    e["counts"]["mev"]    += mv
    e["counts"]["bridges"]+= br
    if ray_prog_hit:
        e["lp_init"] = True

def purge_old(db, window_min):
    # مسح التجميعات لّي مرّات عليها مدة كبيرة
    cutoff = _now() - timedelta(minutes=window_min)
    to_del = []
    for mint, e in db.items():
        try:
            last = datetime.fromisoformat(e["last_seen"])
        except:
            last = _now()
        if last < cutoff:
            to_del.append(mint)
    for mint in to_del:
        del db[mint]

def render_line(mint, e, s):
    c = e.get("counts", {})
    w = c.get("whale", 0); cx = c.get("cex",0); mv = c.get("mev",0); br = c.get("bridges",0)
    lp = "✅" if e.get("lp_init") else "⏳"
    return (
        f"*{mint}* • CrypsScore: *{s}/100* {lp}\n"
        f"🐋 Whales:{w}  🏦 CEX:{cx}  🤖 MEV:{mv}  🌉 Bridges:{br}\n"
        f"[Solscan](https://solscan.io/token/{mint}) | [Dexscreener](https://dexscreener.com/solana/{mint})\n"
    )

# =========[ TELEGRAM WEBHOOK ]=========
@app.route(f"/tg/{TG_SECRET}", methods=["POST"])
def tg_webhook():
    data = request.get_json(force=True, silent=True) or {}
    try:
        msg = data.get("message") or data.get("edited_message") or {}
        chat_id = str(msg.get("chat", {}).get("id", ""))
        text = (msg.get("text") or "").strip()
    except Exception:
        return jsonify({"ok": True})

    # ماكنجاوب إلا إلى كان هاد الشات هو ديالنا
    if CHAT_ID and chat_id and CHAT_ID != chat_id:
        return jsonify({"ok": True})

    if text.lower().startswith("/start"):
        st = load_state()
        st["RUNNING"] = True
        save_state(st)
        tg_send("🟢 *Cryps Ultra Pilot:* شغال دابا.\n\nأوامر مفيدة:\n/winners — يعرض Top 10\n/stop — يوقّف الدفع التلقائي\n/qa <mint> — فحص سريع", True)

    elif text.lower().startswith("/stop"):
        st = load_state()
        st["RUNNING"] = False
        st["ALLOW_AUTO_PUSH"] = False
        save_state(st)
        tg_send("🛑 توقّف. ما غاديش نصايفط حتى تعطي أمر.", True)

    elif text.lower().startswith("/winners"):
        # عرض Top N بناءً على آخر WINDOW_MIN دقيقة
        st = load_state()
        db = load_clusters()
        window = st["WINDOW_MIN"]
        purge_old(db, window)

        # حوّل touchers من set → list قبل التقييم
        for e in db.values():
            if isinstance(e.get("touchers"), set):
                e["touchers"] = list(e["touchers"])

        scored = []
        for mint, e in db.items():
            if is_noise_mint(mint):
                continue
            s = score_entry(e)
            if s >= st["MIN_SCORE"]:
                scored.append((s, mint, e))
        scored.sort(reverse=True, key=lambda x: x[0])

        if not scored:
            tg_send("⏳ ما كاين حتى Winner فـ النافذة ديال الوقت الحالية. جرّب من بعد دقائق.", True)
        else:
            topn = st["TOP_N"]
            out = ["*🏆 Top Winners (last {}m)*".format(window)]
            for i, (s, mint, e) in enumerate(scored[:topn], start=1):
                out.append(f"{i}. " + render_line(mint, e, s))
            tg_send("\n".join(out), False)

    elif text.lower().startswith("/qa"):
        parts = text.split()
        if len(parts) < 2:
            tg_send("استعمال: `/qa <mint>`", True)
        else:
            mint = parts[1].strip()
            db = load_clusters()
            e = db.get(mint)
            if not e:
                tg_send("ما لقيتش بيانات على هاد المينت فقاعدة التجميعات.", True)
            else:
                s = score_entry(e)
                line = render_line(mint, e, s)
                tg_send("🔎 *QA Quick Check*\n" + line, False)

    else:
        tg_send("أوامر: /start /stop /winners /qa <mint>", True)

    return jsonify({"ok": True})

# =========[ HELIUS WEBHOOK ]=========
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    # تأمين الهيدر
    sec = request.headers.get("X-Cryps-Secret", "")
    if HEL_SECRET and sec != HEL_SECRET:
        return jsonify({"ok": False, "err": "bad secret"}), 401

    payload = request.get_json(force=True, silent=True) or {}
    # Helius ممكن يرسل single أو batch events
    events = payload if isinstance(payload, list) else [payload]

    st = load_state()
    with lock:
        db = load_clusters()

        for ev in events:
            # هيكّل الحدث و استخرج المينتات و العناوين الملامسة
            mint_candidates = set()
            touch_addrs = set()
            ray_prog_hit = False

            # 1) من accountData و tokenTransfers و instructions
            accounts = ev.get("accountData") or []
            for a in accounts:
                addr = a.get("account", "")
                if addr:
                    touch_addrs.add(addr)

            # token transfers:
            tts = ev.get("tokenTransfers") or []
            for t in tts:
                mi = t.get("mint")
                if mi: mint_candidates.add(mi)
                src = t.get("fromUserAccount", "")
                dst = t.get("toUserAccount", "")
                for a in (src, dst):
                    if a: touch_addrs.add(a)

            # instructions/programs
            insts = ev.get("instructions") or []
            for ins in insts:
                prog = ins.get("programId", "")
                if prog:
                    touch_addrs.add(prog)
                    if prog in RAYDIUM_PROGRAMS:
                        ray_prog_hit = True
                # بعض الهيكالات عندها inner instructions
                for sub in ins.get("innerInstructions", []) or []:
                    sp = sub.get("programId", "")
                    if sp:
                        touch_addrs.add(sp)
                        if sp in RAYDIUM_PROGRAMS:
                            ray_prog_hit = True

            # 2) فلترة المينتات الكلاسيكية
            mints = [m for m in mint_candidates if not is_noise_mint(m)]
            if not mints:
                continue

            # 3) سجّل لكل مينت
            for mint in mints:
                register_event(db, mint, touch_addrs, ray_prog_hit=ray_prog_hit)

        # تنظيف قديم
        purge_old(db, load_state()["WINDOW_MIN"])

        # حفظ touchers ك list (JSON-safe)
        for e in db.values():
            if isinstance(e.get("touchers"), set):
                e["touchers"] = list(e["touchers"])

        save_clusters(db)

    # ماكنبعت والو تلقائياً إلا إذا فعلتها يدويّاً، باش مانضيّعوش الكريدي
    return jsonify({"ok": True})

# =========[ CONTROL (اختياري) ]=========
@app.route("/control", methods=["POST"])
def control():
    """
    نقطة تحكّم بسيطة (اختيارية) لو بغيت تغيّر إعدادات بلا Telegram.
    JSON:
    { "RUNNING": true/false, "ALLOW_AUTO_PUSH": true/false, "MIN_SCORE": 75, "TOP_N": 10, "WINDOW_MIN": 120 }
    """
    sec = request.headers.get("X-Cryps-Secret", "")
    if HEL_SECRET and sec != HEL_SECRET:
        return jsonify({"ok": False, "err": "bad secret"}), 401
    st = load_state()
    body = request.get_json(force=True, silent=True) or {}
    for k,v in body.items():
        if k in DEFAULT_STATE:
            st[k] = v
    save_state(st)
    return jsonify({"ok": True, "state": st})

@app.route("/health", methods=["GET"])
def health():
    st = load_state()
    return jsonify({"ok": True, "state": st})

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8000"))
    app.run(host="0.0.0.0", port=port)
