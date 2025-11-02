# pilot/winners.py
import json, time

def winners_24h(tokens_path: str, whales_list, limit=10):
    try:
        with open(tokens_path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except Exception:
        return []

    cutoff = time.time() - 86400
    recent = [t for t in db if float(t.get("timestamp",0)) >= cutoff]

    def score(t):
        vol = float(t.get("volume24h",0) or 0)
        wh  = int(t.get("whales",0) or 0)
        return vol + (wh * 1000)

    ranked = sorted(recent, key=score, reverse=True)
    seen = set(); out = []
    for t in ranked:
        m = t.get("mint")
        if not m or m in seen: continue
        seen.add(m)
        out.append(t)
        if len(out) >= limit: break
    return out

