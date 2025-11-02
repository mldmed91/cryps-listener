# pilot/qa.py
def data_consistency(fdv, mcap, supply, price):
    try:
        fdv = float(fdv or 0); mcap = float(mcap or 0)
        supply = float(supply or 0); price = float(price or 0)
        if fdv <= 0 or mcap <= 0 or supply <= 0 or price <= 0: return 0.0
        part1 = abs(fdv - mcap) / fdv
        part2 = abs(mcap - (supply * price)) / mcap
        score = 1.0 - (part1 + part2)
        return max(0.0, min(1.0, score))
    except:
        return 0.0

def formula_check(mcap, supply, price):
    try:
        mcap   = float(mcap or 0); supply = float(supply or 0); price = float(price or 0)
        f1 = (supply * price) - mcap
        f2 = (1_000_000_000 - supply) * price
        res = abs(f1) - f2
        return f1, f2, res
    except:
        return 0.0, 0.0, 0.0

def qa_summary(token):
    price = token.get("price", 0)
    mcap  = token.get("marketcap", 0)
    fdv   = token.get("fdv", 0)
    supply= token.get("supply", 0)

    dcs = data_consistency(fdv, mcap, supply, price)
    f1,f2,res = formula_check(mcap, supply, price)

    if dcs >= 0.998: verdict = "PASS ✅"
    elif dcs >= 0.995: verdict = "WARNING 🟡"
    else: verdict = "FAIL 🔴"

    return dcs, (f1, f2, res), verdict

