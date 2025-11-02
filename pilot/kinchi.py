
# pilot/kinchi.py
import json, time

def kinchi_top(tokens_path: str, whales_list, limit=10):
    # حمل الداتا
    try:
        with open(tokens_path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except Exception:
        return []

    now = time.time()
    # آخر 24 ساعة
    recent = [t for t in db if now - float(t.get("timestamp",0)) <= 86400]

    # Score بسيط: presence ديال الحيتان + حداثة + sol size
    def score(t):
        base  = (t.get("whales",0) or 0) * 2.0
        base += min(3.0, (t.get("sol",0.0) or 0.0) / 5.0)
        age_m = max(1.0, (now - float(t.get("timestamp",0))) / 60.0)
        fresh = 1.0 / (1.0 + (age_m ** 0.25))  # 0..1
        return base + fresh

    ranked = sorted(recent, key=score, reverse=True)
    # رجّع غير mint unique (إلغاء التكرار)
    seen = set(); out = []
    for t in ranked:
        m = t.get("mint")
        if not m or m in seen: continue
        seen.add(m)
        out.append(t)
        if len(out) >= limit: break
    return out
