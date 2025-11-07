# app.py — Cryps Ultra Pilot (Telegram Fix Edition)
# ------------------------------------------------------------
# ENV: BOT_TOKEN, CHAT_ID (optional), HELIUS_SECRET
# Optional: RENDER_EXTERNAL_URL, PORT
# Files: whales.txt, mev.txt (optional)
# ------------------------------------------------------------

import os, json, threading, requests
from datetime import datetime, timedelta, timezone
from flask import Flask, request, jsonify

try:
    from dotenv import load_dotenv
    load_dotenv()
except:
    pass

# ================== CONFIG ==================
BOT_TOKEN  = (os.getenv("BOT_TOKEN") or "").strip()
CHAT_ID    = (os.getenv("CHAT_ID") or "").strip()
HEL_SECRET = (os.getenv("HELIUS_SECRET") or "").strip()
APP_URL    = (os.getenv("RENDER_EXTERNAL_URL") or "").strip()
PORT       = int(os.getenv("PORT") or "10000")

DATA_DIR   = "data"
os.makedirs(DATA_DIR, exist_ok=True)
STATE_FILE = f"{DATA_DIR}/state.json"
CL_DB_FILE = f"{DATA_DIR}/clusters.json"
LOG_FILE   = f"{DATA_DIR}/signals.log"

DEFAULT_STATE = {
    "RUNNING": False,
    "COOLDOWN_SEC": 90,
    "TOP_N": 10,
    "MIN_SCORE": 70,
    "WINDOW_MIN": 120,
    "ALLOW_AUTO_PUSH": False,
    "ACCUM_DAYS": 14,
    "MIN_UNIQUE_DAYS": 5,
    "ACCUM_BONUS": 10
}

NOISE_MINTS = {
    "So11111111111111111111111111111111111111112",
    "EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v",
    "Es9vMFrzaCERmJfrF4H2FYD4KCoNkY11McCe8BenwNYB",
}

RAYDIUM_PROGRAMS = {
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
}

KNOWN_LABELS = {
    "A77HErqtfN1hLLpvZ9pCtu66FEtM8BveoaKbbMoZ4RiR": "CEX.Bitget",
    "ASTyfSima4LLAdDgoFGkgqoKowG1LZFDr9fAQrg7iaJZ": "CEX.MEXC",
    "u6PJ8DtQuPFnfmwHbGFULQ4u4EgjDiyYKjVEsynXq2w": "CEX.Gate",
    "2snHHreXbpJ7UwZxPe37gnUNf7Wx7wv6UKDSR2JckKuS": "deBridge.Bridge",
}

lock = threading.Lock()
def _now(): return datetime.now(timezone.utc)

# ================== HELPERS ==================
def log_line(s):
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(f"[{_now().isoformat()}] {s}\n")
    except:
        pass

def load_state():
    if not os.path.exists(STATE_FILE):
        save_state(DEFAULT_STATE)
    try:
        st = json.load(open(STATE_FILE))
    except:
        st = DEFAULT_STATE.copy()
    for k,v in DEFAULT_STATE.items(): st.setdefault(k,v)
    return st

def save_state(st): json.dump(st, open(STATE_FILE,"w"), indent=2)

def _deserialize(e):
    if isinstance(e.get("touchers"), list): e["touchers"]=set(e["touchers"])
    if isinstance(e.get("unique_days"), list): e["unique_days"]=set(e["unique_days"])
    return e

def load_clusters():
    if not os.path.exists(CL_DB_FILE): json.dump({}, open(CL_DB_FILE,"w"))
    try: db = json.load(open(CL_DB_FILE))
    except: db={}
    for k in db: db[k]=_deserialize(db[k])
    return db

def save_clusters(db):
    js={}
    for m,e in db.items():
        ee=dict(e)
        if isinstance(ee.get("touchers"),set): ee["touchers"]=list(ee["touchers"])
        if isinstance(ee.get("unique_days"),set): ee["unique_days"]=list(ee["unique_days"])
        js[m]=ee
    json.dump(js, open(CL_DB_FILE,"w"), indent=2)

def read_lines(f):
    if not os.path.exists(f): return []
    return [x.strip() for x in open(f,encoding="utf-8") if x.strip() and not x.startswith("#")]

def load_watchlists(): return set(read_lines("whales.txt")), set(read_lines("mev.txt"))

def is_noise_mint(m): return not m or m in NOISE_MINTS or len(m)<20
def ray_prog(p): return p in RAYDIUM_PROGRAMS
def maybe_bridge(a): 
    l=KNOWN_LABELS.get(a,""); return "CEX." in l or "Bridge" in l

# ================== SCORING ==================
def _ensure_entry(db,m):
    if m not in db:
        db[m]={"mint":m,"first_seen":_now().isoformat(),"last_seen":_now().isoformat(),
               "counts":{"whale":0,"cex":0,"mev":0,"bridges":0},
               "lp_init":False,"touchers":set(),"unique_days":set()}
    return db[m]

def score_entry(e):
    c=e["counts"]; base=(c["whale"]*12)+(c["mev"]*10)+(c["bridges"]*14)+(c["cex"]*6)+(8 if e["lp_init"] else 0)
    try:last=datetime.fromisoformat(e["last_seen"])
    except:last=_now()
    decay=max(0.6,1.0-((_now()-last).total_seconds()/14400))
    s=base*decay
    st=load_state()
    uds=e.get("unique_days",set())
    cutoff=(_now()-timedelta(days=st["ACCUM_DAYS"])).date()
    recent=[d for d in uds if datetime.fromisoformat(d).date()>=cutoff]
    if len(recent)>=st["MIN_UNIQUE_DAYS"]: s+=st["ACCUM_BONUS"]
    return int(min(100,round(s)))

def register_event(db,mint,addrs,prog=False,mev=False,cex=False):
    e=_ensure_entry(db,mint); e["last_seen"]=_now().isoformat(); e["unique_days"].add(_now().strftime("%Y-%m-%d"))
    if mev: e["counts"]["mev"]+=1
    if cex: e["counts"]["cex"]+=1; e["counts"]["bridges"]+=1
    if prog: e["lp_init"]=True
    for a in addrs:
        e["touchers"].add(a)
        if maybe_bridge(a): e["counts"]["bridges"]+=1

def winners():
    st=load_state(); db=load_clusters()
    res=[]; cut=_now()-timedelta(minutes=st["WINDOW_MIN"])
    for m,e in db.items():
        if is_noise_mint(m):continue
        try:last=datetime.fromisoformat(e["last_seen"])
        except:last=_now()
        if last<cut:continue
        s=score_entry(e)
        if s>=st["MIN_SCORE"]:res.append((s,m,e))
    res.sort(key=lambda x:x[0],reverse=True)
    return res[:st["TOP_N"]]

def winners_msg():
    w=winners()
    if not w:return "⛔ لا Winners حالياً"
    out=["🏆 *Top Winners*"]
    for i,(s,m,e) in enumerate(w,1):
        out.append(f"{i}. `{m}` — *{s}/100* (days:{len(e['unique_days'])})")
    return "\n".join(out)

# ================== TELEGRAM ==================
def tg_send(txt,md=False,cid=None):
    cid = cid or CHAT_ID
    if not (BOT_TOKEN and cid): return
    url=f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload={"chat_id":cid,"text":txt}
    if md: payload["parse_mode"]="Markdown"; payload["disable_web_page_preview"]=True
    try: requests.post(url,json=payload,timeout=8)
    except Exception as ex: log_line(f"TG err {ex}")

# ================== FLASK ==================
app=Flask(__name__)

@app.get("/")
def root(): return jsonify({"ok":True,"app":"Cryps Ultra Pilot","running":load_state()["RUNNING"]})

@app.post(f"/{BOT_TOKEN}")
def tg_webhook():
    data=request.get_json(silent=True) or {}; msg=data.get("message",{})
    text=(msg.get("text","") or "").strip(); cid=msg.get("chat",{}).get("id")
    if not text:return jsonify({"ok":True})
    st=load_state(); t=text.lower()
    if t in ("/help","help"):
        tg_send("*Commands:*\n/start\n/stop\n/winners\n/history <mint>\n/control key=val\n/add_whale <addr>",True,cid)
    elif t=="/start":
        st["RUNNING"]=True; save_state(st)
        tg_send("✅ Tracking started.",True,cid)
    elif t=="/stop":
        st["RUNNING"]=False; save_state(st)
        tg_send("⛔ Tracking stopped.",True,cid)
    elif t=="/winners":
        tg_send(winners_msg(),True,cid)
    elif t.startswith("/control"):
        try:
            upd={}
            for p in text.split()[1:]:
                if "=" not in p:continue
                k,v=p.split("=",1);k=k.upper()
                if k in ("RUNNING","ALLOW_AUTO_PUSH"): upd[k]=v.lower() in ("1","true","on")
                elif k in ("COOLDOWN_SEC","TOP_N","MIN_SCORE","WINDOW_MIN","ACCUM_DAYS","MIN_UNIQUE_DAYS","ACCUM_BONUS"): upd[k]=int(v)
            st.update(upd); save_state(st)
            tg_send(f"تمّ التحديث:\n`{json.dumps(upd,indent=2)}`",True,cid)
        except Exception as ex: tg_send(f"⚠️ Error: {ex}",True,cid)
    elif t.startswith("/history"):
        parts=text.split()
        if len(parts)<2: tg_send("استعمال: /history <mint>",True,cid)
        else:
            m=parts[1]; db=load_clusters(); e=db.get(m)
            if not e: tg_send("ما لقيتش هاد المينت.",True,cid)
            else:
                s=score_entry(e); uds=e["unique_days"]
                tg_send(f"*{m}*\nDays:{len(uds)}\nScore:{s}/100\nFirst:{e['first_seen']}\nLast:{e['last_seen']}",True,cid)
    elif t.startswith("/add_whale"):
        parts=text.split()
        if len(parts)>1:
            addr=parts[1].strip(); open("whales.txt","a").write(addr+"\n")
            tg_send(f"✅ Added whale: `{addr}`",True,cid)
    else:
        tg_send("أمر غير معروف. جرّب /help",False,cid)
    return jsonify({"ok":True})

@app.post("/hel-webhook")
def hel_webhook():
    if HEL_SECRET and request.headers.get("X-Cryps-Secret","")!=HEL_SECRET:
        return jsonify({"ok":False,"err":"bad secret"}),401
    body=request.get_json(silent=True) or {}
    events=body.get("events") if isinstance(body,dict) else body
    if not isinstance(events,list): events=[body]
    with lock:
        st=load_state(); db=load_clusters(); whales,mev=load_watchlists()
        for ev in events:
            try:
                mint=ev.get("mint") or ev.get("tokenAddress"); program=ev.get("programId") or ev.get("source") or ""
                if not mint:
                    tt=ev.get("tokenTransfers") or []
                    if tt: mint=tt[0].get("mint")
                accs=set(a.get("account","") for a in ev.get("accountData",[]))
                if not mint or is_noise_mint(mint): continue
                addrs=list(accs)[:12]
                is_mev=any(a in mev for a in addrs)
                is_cex=any(maybe_bridge(a) for a in addrs)
                prog_hit=ray_prog(program)
                register_event(db,mint,addrs,prog_hit,is_mev,is_cex)
                if st["ALLOW_AUTO_PUSH"]:
                    e=db[mint]; s=score_entry(e)
                    if s>=st["MIN_SCORE"]:
                        tg_send(f"⚡ New: `{mint}` Score:{s}",True)
            except Exception as ex:
                log_line(f"webhook err {ex}")
        save_clusters(db)
    return jsonify({"ok":True})

if __name__=="__main__":
    if APP_URL and BOT_TOKEN:
        try:
            url=f"https://api.telegram.org/bot{BOT_TOKEN}/setWebhook"
            requests.post(url,json={"url":f"{APP_URL}/{BOT_TOKEN}","allowed_updates":["message"]},timeout=5)
        except Exception as ex:
            log_line(f"setWebhook err {ex}")
    app.run(host="0.0.0.0",port=PORT)
