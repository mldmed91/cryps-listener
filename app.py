# app.py — Cryps Ultra Pilot (Accum Edition, fixed)
# ------------------------------------------------------------
# ENV: BOT_TOKEN, CHAT_ID, HELIUS_SECRET
# Optional: RENDER_EXTERNAL_URL (Render), PORT
# Files (optional): whales.txt, mev.txt
# ------------------------------------------------------------

import os, json, threading
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ====== Config ======
BOT_TOKEN  = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID    = (os.getenv("CHAT_ID") or "").strip()
HEL_SECRET = (os.getenv("HELIUS_SECRET") or "").strip()
APP_URL    = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
PORT       = int(os.getenv("PORT") or "10000")

DATA_DIR   = "data"
STATE_FILE = f"{DATA_DIR}/state.json"
CL_DB_FILE = f"{DATA_DIR}/clusters.json"
LOG_FILE   = f"{DATA_DIR}/signals.log"
os.makedirs(DATA_DIR, exist_ok=True)

# ====== Defaults ======
DEFAULT_STATE = {
    "RUNNING": False,           # ما يخدمش حتى تعطي /start
    "COOLDOWN_SEC": 90,         # anti-spam داخلي (احتياطي)
    "TOP_N": 10,
    "MIN_SCORE": 70,
    "WINDOW_MIN": 120,          # نافذة الوقت لعرض ال Winners
    "ALLOW_AUTO_PUSH": False,   # auto-send للتيلغرام
    "ACCUM_DAYS": 14,           # تراكم داخل X أيام
    "MIN_UNIQUE_DAYS": 5,       # أقل أيام فريدة باش يتحسب bonus
    "ACCUM_BONUS": 10           # البونيس على السكور
}

# Noise / معروفين
NOISE_MINTS = set([
    "So11111111111111111111111111111111111111112",  # WSOL
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",# USDC
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",# USDT
    "zGh48JtNHVBb5evgoZLXwgPD2Qu4MhkWdJLGDAupump",
    "HsfJnaBfRhBUTQCzCpXdL5codokZw6nwwWFnkzeWpump",
    "22bpMFQKeETcpEUid6wLLhjWJeGgqB8uQmub5A7ppump",
])

# Raydium Programs
RAYDIUM_PROGRAMS = set([
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
])

# Labels مختصرة (عينة نافعة)
KNOWN_LABELS = {
    "43DbAvKxhXh1oSxkJSqGosNw3HpBnmsWiak6tB5wpecN": "CEX.Backpack",
    "u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w": "CEX.Gate",
    "ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg7iaJZ": "CEX.MEXC",
    "A77HErqtfN1hLLpvZ9pCtu66FEtM8BveoaKbbMoZ4RiR": "CEX.Bitget",
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "CEX.Binance",
    "ZG98FUCjb8mJ824Gbs6RsgVmr1FhXb2oNiJHa2dwmPd": "BONKbot.Fees",
    "8psNvWTrdNTiVRNzAgsou9kETXNJm2SXZyaKuJraVRtf": "Phantom.Fees",
    "j1oxqtEHFn7rUkdABJLmtVtz5fFmHFs4tCG3fWJnkHX": "Jupiter",
    "HV1KXxWFaSeriyFvXyx48FqG9BoFbfinB8njCJonqP7K": "OKX.DEX.Router",
    "2snHHreXbpJ7UwZxPe37gnUNf7Wx7wv6UKDSR2JckKuS": "deBridge.Bridge",
}

# ====== Utils ======
lock = threading.Lock()
def _now(): return datetime.now(timezone.utc)

def log_line(s: str):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{_now().isoformat()}] {s}\n")
    except Exception:
        pass

def load_state():
    if not os.path.exists(STATE_FILE):
        save_state(DEFAULT_STATE.copy())
    try:
        with open(STATE_FILE, "r") as f:
            st = json.load(f)
    except Exception:
        st = DEFAULT_STATE.copy()
    for k, v in DEFAULT_STATE.items():
        st.setdefault(k, v)
    return st

def save_state(st: dict):
    with open(STATE_FILE, "w") as f:
        json.dump(st, f, indent=2)

def _deserialize_sets(e: dict):
    if isinstance(e.get("touchers"), list):
        e["touchers"] = set(e["touchers"])
    if isinstance(e.get("unique_days"), list):
        e["unique_days"] = set(e["unique_days"])
    return e

def load_clusters():
    if not os.path.exists(CL_DB_FILE):
        with open(CL_DB_FILE, "w") as f:
            json.dump({}, f)
        return {}
    try:
        with open(CL_DB_FILE, "r") as f:
            db = json.load(f)
    except Exception:
        db = {}
    for k in list(db.keys()):
        db[k] = _deserialize_sets(db[k])
    return db

def save_clusters(db: dict):
    serial = {}
    for m, e in db.items():
        ee = dict(e)
        if isinstance(ee.get("touchers"), set):
            ee["touchers"] = list(ee["touchers"])
        if isinstance(ee.get("unique_days"), set):
            ee["unique_days"] = list(ee["unique_days"])
        serial[m] = ee
    with open(CL_DB_FILE, "w") as f:
        json.dump(serial, f, indent=2)

def read_lines(fname: str):
    out = []
    if not os.path.exists(fname): return out
    with open(fname, "r", encoding="utf-8", errors="ignore") as f:
        for ln in f.read().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"): continue
            out.append(ln)
    return out

def load_watchlists():
    whales = set(read_lines("whales.txt"))
    mev    = set(read_lines("mev.txt"))
    return whales, mev

def is_noise_mint(mint: str) -> bool:
    if not mint: return True
    if mint in NOISE_MINTS: return True
    if len(mint) < 20: return True
    return False

def raydium_prog_hit(pid: str) -> bool:
    return pid in RAYDIUM_PROGRAMS

def _maybe_bridge_label(addr: str) -> bool:
    label = KNOWN_LABELS.get(addr, "")
    if not label: return False
    return ("CEX." in label) or ("Bridge" in label)

def _ensure_entry(db, mint):
    if mint not in db:
        db[mint] = {
            "mint": mint,
            "first_seen": _now().isoformat(),
            "last_seen": _now().isoformat(),
            "counts": {"whale":0, "cex":0, "mev":0, "bridges":0},
            "lp_init": False,
            "touchers": set(),
            "unique_days": set()
        }
    return db[mint]

def age_minutes(iso_ts: str) -> float:
    try:
        dt = datetime.fromisoformat(iso_ts)
    except Exception:
        return 0.0
    return max(0.0, (_now() - dt).total_seconds() / 60.0)

# ====== Scoring ======
def score_entry(e: dict) -> int:
    c = e.get("counts", {})
    w  = c.get("whale", 0)
    cx = c.get("cex",   0)
    mv = c.get("mev",   0)
    br = c.get("bridges", 0)
    lp = 1 if e.get("lp_init") else 0

    base = (w*12) + (mv*10) + (br*14) + (cx*6) + (lp*8)
    try: last = datetime.fromisoformat(e["last_seen"])
    except: last = _now()
    decay = max(0.6, 1.0 - (age_minutes(last.isoformat()) / 240.0))
    score = base * decay

    st = load_state()
    acc_days   = st.get("ACCUM_DAYS", 14)
    min_unique = st.get("MIN_UNIQUE_DAYS", 5)
    bonus      = st.get("ACCUM_BONUS", 10)

    uds = e.get("unique_days", set()) or set()
    cutoff = (_now() - timedelta(days=acc_days)).date()
    recent = [d for d in uds if datetime.fromisoformat(d).date() >= cutoff]
    if len(recent) >= min_unique:
        score += bonus

    return int(min(100, round(score)))

def format_signal(e: dict, score: int) -> str:
    mint = e["mint"]
    scan = f"Solscan (https://solscan.io/token/{mint})"
    dskr = f"DexScreener (https://dexscreener.com/solana/{mint})"
    whales, mev = load_watchlists()
    touchers = list(e.get("touchers", []))
    wl = []
    for a in touchers[:6]:
        tag = "#"
        if a in whales: tag = "W"
        if a in mev:    tag = "M"
        wl.append(f"{a[:6]}…{a[-5:]}[{tag}]")
    wl_str = ", ".join(wl) if wl else "—"
    return (
        f"⚡ *CANDIDATE*  •  CrypsScore: *{score}/100*\n"
        f"`{mint}`\n{scan} | {dskr}\n"
        f"👥 Touchers: {wl_str}"
    )

def register_event(db, mint, touch_addrs, ray_prog=False, is_mev=False, is_cex=False):
    e = _ensure_entry(db, mint)
    e["last_seen"] = _now().isoformat()
    e["unique_days"].add(_now().strftime("%Y-%m-%d"))
    if is_mev:
        e["counts"]["mev"] += 1
    if is_cex:
        e["counts"]["cex"] += 1
        e["counts"]["bridges"] += 1
    if ray_prog:
        e["lp_init"] = True
    for a in (touch_addrs or []):
        e["touchers"].add(a)
        if _maybe_bridge_label(a):
            e["counts"]["bridges"] += 1

def compute_winners():
    st = load_state()
    db = load_clusters()
    min_score = int(st.get("MIN_SCORE", 70))
    topn      = int(st.get("TOP_N", 10))
    window    = int(st.get("WINDOW_MIN", 120))
    cutoff    = _now() - timedelta(minutes=window)

    bucket = []
    for m, e in db.items():
        if is_noise_mint(m): 
            continue
        try:  last = datetime.fromisoformat(e["last_seen"])
        except: last = _now()
        if last < cutoff:
            continue
        s = score_entry(e)
        if s >= min_score:
            bucket.append((s, m, e))
    bucket.sort(key=lambda x: x[0], reverse=True)
    return bucket[:topn]

def winners_message():
    wins = compute_winners()
    if not wins:
        return "⛔ ما كايناش Winners فهاد النافذة. جرّب تبدّل الإعدادات بـ /control."
    lines = ["🏆 *Top Winners*"]
    for i, (s, m, e) in enumerate(wins, start=1):
        uds = len(e.get("unique_days", set()))
        lines.append(f"{i}. `{m}` — *{s}/100*  (days:{uds})")
    return "\n".join(lines)

# ====== Telegram ======
def tg_send(text: str, md=False):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {"chat_id": CHAT_ID, "text": text}
    if md:
        payload["parse_mode"] = "Markdown"
        payload["disable_web_page_preview"] = True
    try:
        requests.post(url, json=payload, timeout=8)
    except Exception as ex:
        log_line(f"TG send err: {ex}")

# ====== Flask ======
app = Flask(__name__)

@app.get("/")
def root():
    return jsonify({"ok": True, "app": "Cryps Ultra Pilot (Accum)", "running": load_state().get("RUNNING")})

# Telegram webhook على مسار فيه التوكن (آمن وكافي)
@app.post(f"/{BOT_TOKEN}")
def tg_webhook():
    data = request.get_json(silent=True) or {}
    msg  = data.get("message", {})
    text = (msg.get("text","") or "").strip()
    if not text:
        return jsonify({"ok": True})

    with lock:
        st = load_state()

        t = text.lower()
        if t in ("/help", "help"):
            help_msg = (
                "*Commands*\n"
                "/start — تشغيل التخزين.\n"
                "/stop — توقيف.\n"
                "/winners — عرض أعلى 10.\n"
                "/history <mint> — تاريخ التراكم وscore.\n"
                "/control key=val — تحديث الإعدادات (MIN_SCORE,TOP_N,WINDOW_MIN,COOLDOWN_SEC,ACCUM_DAYS,MIN_UNIQUE_DAYS,ACCUM_BONUS).\n"
                "/add_whale <addr> — إضافة عنوان للحيتان محلياً.\n"
            )
            tg_send(help_msg, True)
            return jsonify({"ok": True})

        if t == "/start":
            st["RUNNING"] = True
            save_state(st)
            tg_send("✅ *RUNNING=True* — كنخزن الإشارات. استعمل /winners باش تشوف الترتيب.", True)
            return jsonify({"ok": True})

        if t == "/stop":
            st["RUNNING"] = False
            save_state(st)
            tg_send("⛔ *RUNNING=False* — طفيناه.", True)
            return jsonify({"ok": True})

        if t == "/winners":
            tg_send(winners_message(), True)
            return jsonify({"ok": True})

        if t.startswith("/history"):
            parts = text.split()
            if len(parts) < 2:
                tg_send("استعمال: `/history <mint>`", True)
            else:
                mint = parts[1].strip()
                db = load_clusters()
                e  = db.get(mint)
                if not e:
                    tg_send("ما لقيتش هاد المينت فالداتابيز.", True)
                else:
                    uds = e.get("unique_days", set()) or set()
                    days_list = sorted(list(uds))
                    cutoff = (_now() - timedelta(days=st.get("ACCUM_DAYS", 14))).date()
                    recent_count = sum(1 for d in days_list if datetime.fromisoformat(d).date() >= cutoff)
                    s = score_entry(e)
                    msg = (
                        f"🗓 *Accumulation History*\n"
                        f"Mint: `{mint}`\n"
                        f"Unique days (total): *{len(days_list)}*\n"
                        f"Unique days (last {st.get('ACCUM_DAYS',14)}d): *{recent_count}*\n"
                        f"First seen: `{e.get('first_seen','-')}`\n"
                        f"Last seen:  `{e.get('last_seen','-')}`\n"
                        f"CrypsScore (now): *{s}/100*"
                    )
                    tg_send(msg, True)
            return jsonify({"ok": True})

        if t.startswith("/control"):
            try:
                pairs = text.split()[1:]
                upd = {}
                for p in pairs:
                    if "=" not in p: continue
                    k, v = p.split("=", 1)
                    k = k.strip().upper()
                    v = v.strip()
                    if k in ("RUNNING","ALLOW_AUTO_PUSH"):
                        upd[k] = v.lower() in ("1","true","yes","on")
                    elif k in ("COOLDOWN_SEC","TOP_N","MIN_SCORE","WINDOW_MIN","ACCUM_DAYS","MIN_UNIQUE_DAYS","ACCUM_BONUS"):
                        upd[k] = int(v)
                st.update(upd)
                save_state(st)
                tg_send(f"تمّ التحديث:\n`{json.dumps(upd, indent=2)}`", True)
            except Exception as ex:
                tg_send(f"خطأ فـ /control: {ex}", True)
            return jsonify({"ok": True})

        if t.startswith("/add_whale"):
            parts = text.split()
            if len(parts) < 2:
                tg_send("استعمال: `/add_whale <address>`", True)
            else:
                addr = parts[1].strip()
                with open("whales.txt", "a") as f:
                    f.write(addr + "\n")
                tg_send(f"✅ تزاد فـ whales: `{addr}`", True)
            return jsonify({"ok": True})

        tg_send("أمر غير معروف. جرّب /help", False)
        return jsonify({"ok": True})

# ====== CSV Backfill ======
@app.post("/import_csv")
def import_csv():
    # حماية بنفس Secret ديال Helius باش ما يتبهدلش الendpoint
    if HEL_SECRET and request.headers.get("X-Cryps-Secret","") != HEL_SECRET:
        return jsonify({"ok": False, "err": "bad secret"}), 401
    if "file" not in request.files:
        return jsonify({"ok": False, "err": "no file"}), 400

    f = request.files["file"]
    lines = f.read().decode("utf-8", errors="ignore").splitlines()
    headers = [h.strip().lower() for h in lines[0].split(",")]

    def idx(col):
        try: return headers.index(col)
        except: return -1

    i_mint = idx("mint")
    i_ts   = idx("timestamp")
    i_addr = idx("address")
    if min(i_mint, i_ts, i_addr) < 0:
        return jsonify({"ok": False, "err": "missing mint,timestamp,address"}), 400

    with lock:
        db = load_clusters()
        cnt = 0
        for row in lines[1:]:
            parts = row.split(",")
            if len(parts) < len(headers): continue
            mint = parts[i_mint].strip()
            if not mint or is_noise_mint(mint): continue
            ts   = parts[i_ts].strip().replace("Z","+00:00")
            addr = parts[i_addr].strip()

            e = _ensure_entry(db, mint)
            e["last_seen"] = ts
            try:
                day_key = datetime.fromisoformat(ts).strftime("%Y-%m-%d")
            except Exception:
                day_key = _now().strftime("%Y-%m-%d")
            e["unique_days"].add(day_key)
            if addr:
                e["touchers"].add(addr)
            cnt += 1
        save_clusters(db)

    return jsonify({"ok": True, "imported_rows": cnt})

# ====== Helius Webhook ======
@app.post("/hel-webhook")
def hel_webhook():
    if HEL_SECRET and request.headers.get("X-Cryps-Secret","") != HEL_SECRET:
        return jsonify({"ok": False, "err": "bad secret"}), 401

    body = request.get_json(silent=True) or {}
    # Enhanced webhook غالباً: {"events":[ ... ]}
    if isinstance(body, dict) and isinstance(body.get("events"), list):
        events = body["events"]
    elif isinstance(body, list):
        events = body
    else:
        events = [body]

    with lock:
        st = load_state()
        db = load_clusters()
        whales, mev = load_watchlists()

        for ev in events:
            try:
                accs = set()
                mint = ev.get("mint") or ev.get("token") or ev.get("tokenAddress")
                program = ev.get("programId") or ev.get("source") or ""

                # tokenTransfers → mint
                tt = ev.get("tokenTransfers") or []
                if not mint and tt and isinstance(tt, list):
                    mint = tt[0].get("mint")

                # accountData
                ad = ev.get("accountData") or []
                for a in ad:
                    accs.add(a.get("account",""))

                # transactions
                txs = ev.get("transactions") or []
                for t in txs:
                    for a in t.get("accountData", []):
                        accs.add(a.get("account",""))
                    program = t.get("programId", program)
                    if not mint:
                        tt2 = t.get("tokenTransfers") or []
                        if tt2:
                            mint = tt2[0].get("mint")

                if not mint or is_noise_mint(mint):
                    continue

                addrs = list(accs)[:12]
                is_mev = any(a in mev for a in addrs)
                is_cex = any(_maybe_bridge_label(a) for a in addrs)
                prog_hit = raydium_prog_hit(program)

                register_event(db, mint, addrs, ray_prog=prog_hit, is_mev=is_mev, is_cex=is_cex)

                if st.get("ALLOW_AUTO_PUSH", False):
                    e = db.get(mint)
                    s = score_entry(e)
                    if s >= st.get("MIN_SCORE", 70):
                        tg_send(format_signal(e, s), True)

            except Exception as ex:
                log_line(f"webhook err: {ex}")
                continue

        save_clusters(db)

    return jsonify({"ok": True})

# ====== Boot ======
if __name__ == "__main__":
    # سجلّ Webhook ديال تيليجرام للمسار /<BOT_TOKEN>
    if APP_URL and BOT_TOKEN:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
            requests.post(
                url,
                json={"url": f"{APP_URL}/{BOT_TOKEN}", "allowed_updates": ["message"]},
                timeout=5
            )
        except Exception as ex:
            log_line(f"setWebhook err: {ex}")

    app.run(host="0.0.0.0", port=PORT)
