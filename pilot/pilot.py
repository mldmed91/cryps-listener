# pilot/pilot.py
import json, time, os, math
from collections import defaultdict
DATA = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

def _load(path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f) if path.endswith(".json") else f.read().splitlines()
    except:
        return default

def _save(path, data):
    with open(path, "w", encoding="utf-8") as f:
        return json.dump(data, f, ensure_ascii=False, indent=2) if path.endswith(".json") else f.write("\n".join(data))

def now(): return int(time.time())

# ـــــــــــــــــــــــ Inputs ـــــــــــــــــــــــ
def load_whales():
    return set([w.strip() for w in _load(os.path.join(DATA, "whales.txt"), []) if w.strip()])

def load_tokens_cache():
    path = os.path.join(DATA, "tokens.json")
    cache = _load(path, {"tokens": {}, "events": []})
    if "tokens" not in cache: cache["tokens"] = {}
    if "events" not in cache: cache["events"] = []
    return cache

def save_tokens_cache(cache):
    _save(os.path.join(DATA, "tokens.json"), cache)

def append_signal(line):
    with open(os.path.join(DATA, "signals.log"), "a", encoding="utf-8") as f:
        f.write(line.rstrip()+"\n")

# ـــــــــــــــــــــــ Ingestion من Helius ـــــــــــــــــــــــ
def ingest_txn(tx):
    """
    tx: dict من /hel-webhook (Helius Enhanced) – نركبو واحد الحد الأدنى لي كنحتاجوه
    """
    sig = tx.get("signature","")
    ts  = tx.get("timestamp") or now()
    ttype = tx.get("type","")  # TRANSFER / SWAP / TOKEN_MINT / CREATE...
    nat  = 0.0
    for n in tx.get("nativeTransfers", []):
        nat += (n.get("amount",0) or 0)/1e9

    # mint address (if swap/mint) – heuristics بسيطة
    mint = None
    if tx.get("tokenTransfers"):
        mints = [tt.get("mint") for tt in tx["tokenTransfers"] if tt.get("mint")]
        mint = mints[0] if mints else None

    accounts = set([a.get("account") for a in tx.get("accounts",[]) if a.get("account")])
    return {
        "sig": sig, "ts": ts, "type": ttype, "sol": nat, "mint": mint, "accounts": list(accounts)
    }

# ـــــــــــــــــــــــ Scoring ـــــــــــــــــــــــ
def score_engine(cache, whales):
    """
    نحسبو Scores لكل mint على اساس:
    - WhaleInflow (عدد وحيتان/حجم SOL)
    - Freshness (الأحداث الأخيرة أعلى)
    - Diversity (عدد حسابات مختلفين)
    """
    tokens = defaultdict(lambda: {"whale_in":0, "sol_in":0.0, "events":0, "accounts":set(), "last_ts":0})

    for e in cache["events"]:
        m = e.get("mint")
        if not m: continue
        info = tokens[m]
        # whale check
        if any(acc in whales for acc in e.get("accounts",[])):
            info["whale_in"] += 1
            info["sol_in"]   += max(0.0, e.get("sol",0.0))
        info["events"]  += 1
        info["accounts"].update(e.get("accounts",[]))
        info["last_ts"]  = max(info["last_ts"], e.get("ts",0))

    scored = []
    now_ts = now()
    for mint, d in tokens.items():
        age_min = max(1, (now_ts - d["last_ts"]) / 60.0)
        fresh = 1.0 / (1.0 + math.log10(age_min))     # 0..1
        diversity = min(1.0, len(d["accounts"]) / 10) # 0..1

        whaleScore = d["whale_in"]*2 + d["sol_in"]/10
        metaScore  = d["events"]*0.5 + diversity*2
        total = round( (whaleScore*0.6 + metaScore*0.3 + fresh*3)*10 )/10.0

        scored.append({
            "mint": mint,
            "whale_in": d["whale_in"],
            "sol_in": round(d["sol_in"],2),
            "events": d["events"],
            "diversity": round(diversity,2),
            "fresh": round(fresh,2),
            "score": total,
            "last_ts": d["last_ts"],
        })
    return sorted(scored, key=lambda x: (-x["score"], -x["last_ts"]))[:20]

# ـــــــــــــــــــــــ API بسيطة للموديول ـــــــــــــــــــــــ
def pilot_add_event(tx):
    whales = load_whales()
    cache  = load_tokens_cache()
    cache["events"].append(tx)
    # حافظ فقط على آخر 5,000 حدث لتخفيف الحجم
    cache["events"] = cache["events"][-5000:]
    save_tokens_cache(cache)

    # log اختياري
    append_signal(f"[EVENT] {tx['type']} mint={tx.get('mint')} sol={tx.get('sol',0)} sig={tx['sig']}")
    return True

def pilot_top_winners():
    whales = load_whales()
    cache  = load_tokens_cache()
    winners = score_engine(cache, whales)
    _save(os.path.join(DATA, "winners.json"), winners)
    return winners[:10]

