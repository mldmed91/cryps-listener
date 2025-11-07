# app.py — Cryps Ultra Pilot (Accum60 Edition)
# ------------------------------------------------------------
# ENV vars: BOT_TOKEN, CHAT_ID, TG_SECRET, HELIUS_SECRET
# Optional: RENDER_EXTERNAL_URL (Render auto), PORT
# Files used if موجودين: whales.txt, mev.txt
# ------------------------------------------------------------

import os, json, time, threading
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify
import requests

try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# ====== Config ======
BOT_TOKEN     = os.getenv("BOT_TOKEN","").strip()
CHAT_ID       = os.getenv("CHAT_ID","").strip()
TG_SECRET     = os.getenv("TG_SECRET","").strip()   # لحماية /tg
HEL_SECRET    = os.getenv("HELIUS_SECRET","").strip()  # لحماية /hel-webhook
APP_URL       = os.getenv("RENDER_EXTERNAL_URL","").strip()
PORT          = int(os.getenv("PORT","10000"))

STATE_FILE    = "data/state.json"
CLUSTERS_DB   = "data/clusters.json"
LOG_FILE      = "data/signals.log"

os.makedirs("data", exist_ok=True)

# ====== Defaults ======
DEFAULT_STATE = {
    "RUNNING": False,         # ما كيخدمش حتى تعطي أمر
    "COOLDOWN_SEC": 90,       # لتفادي السبام
    "TOP_N": 10,              # فـ /winners
    "MIN_SCORE": 70,          # أقل سكور باش يبان فـ /winners
    "WINDOW_MIN": 120,        # نافذة التحليل بالـ دقائق
    "ALLOW_AUTO_PUSH": False, # مايبعتش للتيلغرام تلقائياً
    # Accumulation Window
    "ACCUM_DAYS": 2,
    "MIN_UNIQUE_DAYS": 2,    # زيدها 12..15 إذا بغيتي تشدد
    "ACCUM_BONUS": 2         # بونيس فالسكور إذا توفّر تراكم الأيام
}

NOISE_MINTS = set([
    # WSOL / USDC / USDT وغيرها
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
    # أمثلة "pump" المزيفة
    "zGh48JtNHVBb5evgoZLXwgPD2Qu4MhkWdJLGDAupump",
    "HsfJnaBfRhBUTQCzCpXdL5codokZw6nwwWFnkzeWpump",
    "22bpMFQKeETcpEUid6wLLhjWJeGgqB8uQmub5A7ppump"
])

# Raydium Programs (Mainnet)
RAYDIUM_PROGRAMS = set([
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",  # CPMM
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",  # Legacy v4
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",  # CLMM
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj"   # LaunchLab
])

# بعض Hot wallets/CEX/Bridges/Fees (عينة):
KNOWN_LABELS = {
    "43DbAvKxhXh1oSxkJSqGosNw3HpBnmsWiak6tB5wpecN": "CEX.Backpack",
    "u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w": "CEX.Gate",
    "ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg7iaJZ": "CEX.MEXC",
    "A77HErqtfN1hLLpvZ9pCtu66FEtM8BveoaKbbMoZ4RiR": "CEX.Bitget",
    "5tzFkiKscXHK5ZXCGbXZxdw7gTjjD1mBwuoFbhUvuAi9": "CEX.Binance",
    "HLnpSz9h2S4hiLQ43rnSD9XkcUThA7B8hQMKmDaiTLcC": "Meteora.Auth",
    "8psNvWTrdNTiVRNzAgsou9kETXNJm2SXZyaKuJraVRtf": "Phantom.Fees",
    "j1oxqtEHFn7rUkdABJLmtVtz5fFmHFs4tCG3fWJnkHX": "Jupiter",
    "j1oAbxxiDUWvoHxEDhWE7THLjEkDQW2cSHYn2vttxTF": "Jupiter.Limit",
    "HV1KXxWFaSeriyFvXyx48FqG9BoFbfinB8njCJonqP7K": "OKX.DEX.Router",
    "ZG98FUCjb8mJ824Gbs6RsgVmr1FhXb2oNiJHa2dwmPd": "BONKbot.Fees",
    "F7p3dFrjRTbtRp8FRF6qHLomXbKRBzpvBLjtQcfcgmNe": "Relay.Solver",
    "GpMZbSM2GgvTKHJirzeGfMFoaZ8UR2X7F4v8vHTvxFbL": "Raydium.Vault",
    "45ruCyfdRkWpRNGEqWzjCiXRHkZs8WXCLQ67Pnpye7Hp": "Jupiter.RefVault",
    "25mYnjJ2MXHZH6NvTTdA63JvjgRVcuiaj6MRiEQNs1Dq": "Phantom.SwapFees",
    "j1oeQoPeuEDmjvyMwBmCWexzCQup77kbKKxV59CnYbd": "Jupiter.Limit2",
    "2snHHreXbpJ7UwZxPe37gnUNf7Wx7wv6UKDSR2JckKuS": "deBridge.Bridge"
}

# ====== Globals ======
lock = threading.Lock()

def _now():
    return datetime.now(timezone.utc)

def load_state():
    if not os.path.exists(STATE_FILE):
        save_state(DEFAULT_STATE.copy())
    try:
        with open(STATE_FILE,"r") as f:
            st = json.load(f)
    except Exception:
        st = DEFAULT_STATE.copy()
    # ensure defaults exist
    for k,v in DEFAULT_STATE.items():
        if k not in st:
            st[k]=v
    return st

def save_state(st):
    with open(STATE_FILE,"w") as f:
        json.dump(st, f, indent=2)

def load_clusters():
    if not os.path.exists(CLUSTERS_DB):
        with open(CLUSTERS_DB,"w") as f:
            json.dump({}, f)
        return {}
    try:
        with open(CLUSTERS_DB,"r") as f:
            db = json.load(f)
    except Exception:
        db = {}
    # restore sets
    for m,e in db.items():
        if isinstance(e.get("touchers"), list):
            e["touchers"] = set(e["touchers"])
        if isinstance(e.get("unique_days"), list):
            e["unique_days"] = set(e["unique_days"])
    return db

def save_clusters(db):
    serializable = {}
    for m,e in db.items():
        ee = dict(e)
        if isinstance(ee.get("touchers"), set):
            ee["touchers"] = list(ee["touchers"])
        if isinstance(ee.get("unique_days"), set):
            ee["unique_days"] = list(ee["unique_days"])
        serializable[m] = ee
    with open(CLUSTERS_DB, "w") as f:
        json.dump(serializable, f, indent=2)

def log_line(s):
    try:
        with open(LOG_FILE,"a",encoding="utf-8") as log:
            log.write(f"[{_now().isoformat()}] {s}\n")
    except Exception:
        pass

# ====== Files: whales.txt / mev.txt ======
def read_lines(fname):
    out = []
    if not os.path.exists(fname): return out
    with open(fname,"r",encoding="utf-8", errors="ignore") as f:
        for ln in f.read().splitlines():
            ln = ln.strip()
            if not ln or ln.startswith("#"): continue
            out.append(ln)
    return out

def load_watchlists():
    whales = set(read_lines("whales.txt"))
    mev    = set(read_lines("mev.txt"))
    return whales, mev

# ====== Helpers ======
def is_noise_mint(mint:str)->bool:
    if mint in NOISE_MINTS: return True
    if len(mint)<20: return True
    return False

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

def _maybe_bridge_label(addr:str)->bool:
    # أي عنوان معروف من KNOWN_LABELS فيه CEX أو Bridge يعتبر bridge/cex touch
    label = KNOWN_LABELS.get(addr, "")
    if not label: return False
    return ("CEX." in label) or ("Bridge" in label)

def raydium_prog_hit(prog:str)->bool:
    return prog in RAYDIUM_PROGRAMS

def age_minutes(iso_ts):
    try:
        dt = datetime.fromisoformat(iso_ts)
    except Exception:
        return 0
    return max(0, (_now()-dt).total_seconds()/60.0)

def whatsapp_round(x):  # just nicer int clamp
    try:
        return int(round(float(x)))
    except: 
        return 0

# ====== Scoring (with Accum60) ======
def score_entry(e):
    c = e.get("counts", {})
    w  = c.get("whale", 0)
    cx = c.get("cex",   0)
    mv = c.get("mev",   0)
    br = c.get("bridges",0)
    lp = 1 if e.get("lp_init") else 0

    base = (w*12) + (mv*10) + (br*14) + (cx*6) + (lp*8)

    try:
        last = datetime.fromisoformat(e["last_seen"])
    except:
        last = _now()
    dec = max(0.6, 1.0 - (age_minutes(last.isoformat())/240.0))
    score = base * dec

    st = load_state()
    acc_days   = st.get("ACCUM_DAYS",60)
    min_unique = st.get("MIN_UNIQUE_DAYS",10)
    bonus      = st.get("ACCUM_BONUS",18)

    uds = e.get("unique_days", set()) or set()
    cutoff = (_now() - timedelta(days=acc_days)).date()
    recent = [d for d in uds if datetime.fromisoformat(d).date() >= cutoff]
    if len(recent) >= min_unique:
        score += bonus

    return int(min(100, round(score)))

def format_signal(e, score:int):
    mint = e["mint"]
    scan = f"Solscan (https://solscan.io/token/{mint})"
    dskr = f"DexScreener (https://dexscreener.com/solana/{mint})"
    # basic label of whales in touchers
    touchers = list(e.get("touchers", []))
    wl = []
    whales, mev = load_watchlists()
    for a in touchers[:6]:
        tag = "#"
        if a in whales: tag = "W"
        if a in mev:    tag = "M"
        short = f"{a[:6]}…{a[-5:]}[{tag}]"
        wl.append(short)
    wl_str = ", ".join(wl) if wl else "—"

    return (
        f"⚡ *CANDIDATE*  •  CrypsScore: *{score}/100*\n"
        f"`{mint}`\n{scan} | {dskr}\n"
        f"👥 Touchers: {wl_str}"
    )

# ====== Register Events ======
def register_event(db, mint, touch_addrs, ray_prog_hit=False, is_mev=False, is_cex=False):
    e = _ensure_entry(db, mint)
    e["last_seen"] = _now().isoformat()
    # unique day
    e["unique_days"].add(_now().strftime("%Y-%m-%d"))
    # counters
    if is_mev:
        e["counts"]["mev"] += 1
    if is_cex:
        e["counts"]["cex"] += 1
        e["counts"]["bridges"] += 1  # نعطيها bridge touch لأن المصدر CEX/Bridge
    if ray_prog_hit:
        e["lp_init"] = True
    # touchers
    for a in (touch_addrs or []):
        e["touchers"].add(a)
        # heuristics: إذا العنوان معروف CEX/Bridge زيد bridges
        if _maybe_bridge_label(a):
            e["counts"]["bridges"] += 1

# ====== Winners ======
def compute_winners():
    st = load_state()
    db = load_clusters()
    min_score = int(st.get("MIN_SCORE",70))
    topn      = int(st.get("TOP_N",10))
    window    = int(st.get("WINDOW_MIN",120))
    cutoff    = _now() - timedelta(minutes=window)

    bucket = []
    for m,e in db.items():
        if is_noise_mint(m): 
            continue
        try:
            last = datetime.fromisoformat(e["last_seen"])
        except:
            last = _now()
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
        return "لا يوجد Winners فهاذ النافذة (جرّب تزير الشروط أو وسّع WINDOW_MIN)."
    lines = ["🏆 *Top Winners*"]
    rank=1
    for s,m,e in wins:
        uds = len(e.get("unique_days",set()))
        lines.append(f"{rank}. `{m}`  — *{s}/100*  (days:{uds})")
        rank+=1
    return "\n".join(lines)

# ====== Telegram ======
def tg_send(text, md=False):
    if not BOT_TOKEN or not CHAT_ID: return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text": text
    }
    if md:
        payload["parse_mode"]="Markdown"
        payload["disable_web_page_preview"]=True
    try:
        requests.post(url, json=payload, timeout=10)
    except Exception as ex:
        log_line(f"TG send err: {ex}")

# ====== Flask ======
app = Flask(__name__)

@app.route("/")
def index():
    return jsonify({"ok":True, "app":"Cryps Ultra Pilot — Accum60", "running": load_state().get("RUNNING")})

# Telegram webhook (اختياري، تقدّر تستعمل getUpdates)
@app.route("/tg", methods=["POST"])
def tg_webhook():
    if TG_SECRET and request.headers.get("X-TG-Secret","") != TG_SECRET:
        return jsonify({"ok":False, "err":"bad secret"}), 401

    data = request.json or {}
    msg = data.get("message", {})
    text = (msg.get("text","") or "").strip()
    if not text: 
        return jsonify({"ok":True})

    with lock:
        st = load_state()

        # /help
        if text.lower() in ("/help","help"):
            help_msg = (
                "*Commands*\n"
                "/start — تشغيل التتبع (ماكاينش auto push).\n"
                "/stop — إيقاف كامل.\n"
                "/winners — أعلى 10 بمقاييسك.\n"
                "/history <mint> — تاريخ الأيام الفريدة وسكور.\n"
                "/control key=val — تحديث إعدادات (MIN_SCORE,TOP_N,WINDOW_MIN,COOLDOWN_SEC,ACCUM_DAYS,MIN_UNIQUE_DAYS,ACCUM_BONUS).\n"
                "/add_whale <addr> — زيد عنوان للائحة الحيتان (محلياً).\n"
            )
            tg_send(help_msg, True)
            return jsonify({"ok":True})

        # /start
        if text.lower() == "/start":
            st["RUNNING"]=True
            save_state(st)
            tg_send("✅ *RUNNING = True* — غادي نخزّن الإشارات فقط. استعمل /winners باش تشوف الترتيب.", True)
            return jsonify({"ok":True})

        # /stop
        if text.lower() == "/stop":
            st["RUNNING"]=False
            save_state(st)
            tg_send("⛔ *RUNNING = False* — تمّ التوقيف. ماكاع نبعث حتى حاجة حتى تعاود تشغّل.", True)
            return jsonify({"ok":True})

        # /winners
        if text.lower() == "/winners":
            tg_send(winners_message(), True)
            return jsonify({"ok":True})

        # /history <mint>
        if text.lower().startswith("/history"):
            parts = text.split()
            if len(parts)<2:
                tg_send("استعمال: `/history <mint>`", True)
            else:
                mint = parts[1].strip()
                db = load_clusters()
                e  = db.get(mint)
                if not e:
                    tg_send("ما لقيتش هاد المينت فقاعدة البيانات.", True)
                else:
                    uds = e.get("unique_days", set()) or set()
                    days_list = sorted(list(uds))
                    first_seen = e.get("first_seen","-")
                    last_seen  = e.get("last_seen","-")
                    st = load_state()
                    cutoff = (_now() - timedelta(days=st.get("ACCUM_DAYS",60))).date()
                    recent_count = sum(1 for d in days_list if datetime.fromisoformat(d).date() >= cutoff)
                    s = score_entry(e)
                    msg = (
                        f"🗓 *Accumulation History*\n"
                        f"Mint: `{mint}`\n"
                        f"Unique days (total): *{len(days_list)}*\n"
                        f"Unique days (last {st.get('ACCUM_DAYS',60)}d): *{recent_count}*\n"
                        f"First seen: `{first_seen}`\n"
                        f"Last seen:  `{last_seen}`\n"
                        f"CrypsScore (now): *{s}/100*"
                    )
                    tg_send(msg, True)
            return jsonify({"ok":True})

        # /control key=val
        if text.lower().startswith("/control"):
            try:
                pairs = text.split()[1:]
                upd = {}
                for p in pairs:
                    if "=" not in p: continue
                    k,v = p.split("=",1)
                    k=k.strip().upper()
                    v=v.strip()
                    if k in ("RUNNING","ALLOW_AUTO_PUSH"):
                        upd[k] = (v.lower() in ("1","true","yes","on"))
                    elif k in ("COOLDOWN_SEC","TOP_N","MIN_SCORE","WINDOW_MIN","ACCUM_DAYS","MIN_UNIQUE_DAYS","ACCUM_BONUS"):
                        upd[k] = int(v)
                st.update(upd)
                save_state(st)
                tg_send(f"تمّ التحديث:\n`{json.dumps(upd, indent=2)}`", True)
            except Exception as ex:
                tg_send(f"خطأ فـ /control: {ex}", True)
            return jsonify({"ok":True})

        # /add_whale <addr>
        if text.lower().startswith("/add_whale"):
            parts = text.split()
            if len(parts)<2:
                tg_send("استعمال: `/add_whale <address>`", True)
            else:
                addr = parts[1].strip()
                # append to whales.txt
                with open("whales.txt","a") as f:
                    f.write(addr+"\n")
                tg_send(f"✅ تزاد للحيتان: `{addr}`", True)
            return jsonify({"ok":True})

        # else:
        tg_send("أمر غير معروف. جرّب /help", False)
        return jsonify({"ok":True})

# ====== Import CSV (Backfill 60d history) ======
@app.route("/import_csv", methods=["POST"])
def import_csv():
    sec = request.headers.get("X-Cryps-Secret","")
    if HEL_SECRET and sec != HEL_SECRET:
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
        return jsonify({"ok": False, "err": "missing columns mint,timestamp,address"}), 400

    with lock:
        db = load_clusters()
        cnt=0
        for row in lines[1:]:
            parts = row.split(",")
            if len(parts)<len(headers): continue
            mint = parts[i_mint].strip()
            if not mint or is_noise_mint(mint): 
                continue
            ts   = parts[i_ts].strip().replace("Z","+00:00")
            addr = parts[i_addr].strip()

            e = _ensure_entry(db, mint)
            e["last_seen"] = ts
            try:
                day_key = datetime.fromisoformat(ts).strftime("%Y-%m-%d")
            except:
                day_key = _now().strftime("%Y-%m-%d")
            e["unique_days"].add(day_key)
            if addr:
                e["touchers"].add(addr)
            cnt+=1

        save_clusters(db)

    return jsonify({"ok":True, "imported_rows": cnt})

# ====== Helius Webhook ======
@app.route("/hel-webhook", methods=["POST"])
def hel_webhook():
    # أمن
    if HEL_SECRET and request.headers.get("X-Cryps-Secret","") != HEL_SECRET:
        return jsonify({"ok":False, "err":"bad secret"}), 401

    with lock:
        st = load_state()
        if not st.get("RUNNING", False):
            # نخزن فقط، ما كنرسلش للتيلغرام
            pass

        payload = request.json or []
        if isinstance(payload, dict):
            payload = [payload]

        db = load_clusters()
        whales, mev = load_watchlists()

        for ev in payload:
            # Helius Enhanced webhook structure (تبسيط)
            # نحاولو نستخرجو mint/program/ addresses
            try:
                accs = set()
                mint = None
                program = None
                # حسب نوع الحدث
                if "accountData" in ev:  # بعض صيغ
                    for a in ev.get("accountData", []):
                        accs.add(a.get("account",""))
                if "transactions" in ev:
                    for t in ev["transactions"]:
                        for a in t.get("accountData",[]):
                            accs.add(a.get("account",""))
                        program = t.get("programId","") or program
                        mint = t.get("tokenTransfers",[{}])[0].get("mint") or mint
                # بدائل عامة
                if not mint:
                    mint = ev.get("mint") or ev.get("token") or ev.get("tokenAddress")
                if not program:
                    program = ev.get("programId") or ev.get("source","")

                if not mint or is_noise_mint(mint):
                    continue

                # تصنيفات
                addrs = list(accs)[:12]
                is_mev = any(a in mev for a in addrs)
                touch_is_cex = any(_maybe_bridge_label(a) for a in addrs)
                prog_hit = raydium_prog_hit(program)

                register_event(db, mint, addrs, ray_prog_hit=prog_hit, is_mev=is_mev, is_cex=touch_is_cex)

                # بناء رسالة فقط إن ALLOW_AUTO_PUSH True
                if st.get("ALLOW_AUTO_PUSH", False):
                    e = db.get(mint)
                    s = score_entry(e)
                    if s >= st.get("MIN_SCORE",70):
                        tg_send(format_signal(e, s), True)

            except Exception as ex:
                log_line(f"webhook err: {ex}")
                continue

        save_clusters(db)

    return jsonify({"ok":True})

# ====== Run ======
if __name__ == "__main__":
    # Tip: set Telegram webhook once (اختياري)
    # إذا بغيت polling، ماتحتاجش webhook.
    if APP_URL and BOT_TOKEN and TG_SECRET:
        try:
            url = f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
            requests.post(url, json={"url": f"{APP_URL}/tg", "allowed_updates":["message"]}, timeout=5)
        except Exception:
            pass
    app.run(host="0.0.0.0", port=PORT)
