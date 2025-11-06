# app.py
# -*- coding: utf-8 -*-

import os
import time
import json
import hmac
import hashlib
from datetime import datetime, timedelta
from collections import deque, defaultdict

from flask import Flask, request, jsonify, abort

# dotenv اختياري
try:
    from dotenv import load_dotenv  # type: ignore
    load_dotenv()
except Exception:
    pass

import requests

# -----------------------------
# ENV
# -----------------------------
BOT_TOKEN         = os.getenv("BOT_TOKEN", "").strip()
CHAT_ID           = os.getenv("CHAT_ID", "").strip()
HELIUS_API_KEY    = os.getenv("HELIUS_API_KEY", "").strip()
HEL_SECRET        = os.getenv("HEL_SECRET", "cryps_secret").strip()
PUBLIC_BASE_URL   = os.getenv("PUBLIC_BASE_URL", "").strip()
WHALES_FILE       = os.getenv("WHALES_FILE", "data/whales.txt").strip()

if not BOT_TOKEN or not CHAT_ID:
    print("[WARN] BOT_TOKEN/CHAT_ID not set: Telegram messages will be skipped.")

# -----------------------------
# CONSTANTS / RAYDIUM PROGRAMS
# -----------------------------
RAYDIUM_PROGRAMS = {
    # Legacy AMM v4 (CP)
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    # CPMM (Constant Product)
    "CPMMoo8L3F4NbTegBCKVNunggL7H1ZpdTHKxQB5qKP1C",
    # CLMM (Concentrated Liquidity)
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    # LaunchLab
    "LanMV9sAd7wArD4vJFi2qDdfnVhFxYSUg6eADduJ3uj",
}

SOLSCAN_TX   = "https://solscan.io/tx/{}"
SOLSCAN_MINT = "https://solscan.io/token/{}"
DEXSCREENER  = "https://dexscreener.com/solana/{}"

# -----------------------------
# DATA: whales
# -----------------------------
def load_whales(path: str) -> set:
    addrs = set()
    try:
        with open(path, "r", encoding="utf-8") as f:
            for line in f:
                a = line.strip()
                if a and not a.startswith("#"):
                    addrs.add(a)
        print(f"[OK] Loaded whales: {len(addrs)} from {path}")
    except Exception as e:
        print(f"[WARN] whales file not loaded: {e}")
    return addrs

WHALES = load_whales(WHALES_FILE)

# -----------------------------
# UTILS
# -----------------------------
S = requests.Session()
S.headers.update({"User-Agent": "Cryps-Ultra-Pilot/1.0"})

def tg_send(text: str, preview: bool = True):
    if not (BOT_TOKEN and CHAT_ID):
        return
    url = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": CHAT_ID,
        "text"   : text,
        "parse_mode": "HTML",
        "disable_web_page_preview": not preview,
    }
    try:
        S.post(url, json=payload, timeout=10)
    except Exception as e:
        print(f"[WARN] telegram send failed: {e}")

def human_usd(v):
    try:
        v = float(v)
    except Exception:
        return "-"
    if v >= 1_000_000:
        return f"${v/1_000_000:.2f}M"
    if v >= 1_000:
        return f"${v/1_000:.2f}k"
    return f"${v:.2f}"

def get_dex_stats(mint: str):
    """Quick stats from Dexscreener pair (if available)."""
    try:
        r = S.get(f"https://api.dexscreener.com/latest/dex/tokens/{mint}", timeout=6)
        if r.status_code != 200:
            return {}
        data = r.json()
        pairs = data.get("pairs") or []
        # choose best pair (highest liquidity)
        best = None
        best_l = -1
        for p in pairs:
            l = float(p.get("liquidity", {}).get("usd", 0) or 0)
            if l > best_l:
                best = p
                best_l = l
        if not best:
            return {}
        return {
            "liquidity_usd": float(best.get("liquidity", {}).get("usd", 0) or 0),
            "h24_volume_usd": float(best.get("volume", {}).get("h24", 0) or 0),
            "txns_h1": int(best.get("txns", {}).get("h1", {}).get("buys", 0)) + int(best.get("txns", {}).get("h1", {}).get("sells", 0)),
            "pair_url": best.get("url") or f"{DEXSCREENER.format(mint)}",
        }
    except Exception:
        return {}

def any_raydium_program(account_keys: list) -> bool:
    return any(a in RAYDIUM_PROGRAMS for a in account_keys or [])

# -----------------------------
# SCORING
# -----------------------------
def compute_cryps_score(mint: str, account_keys: list, owners: set) -> (int, dict):
    """
    Score (0..12) based on whale convergence + raydium + market hints.
    """
    score = 0
    details = {}

    # 1) Whale convergence
    whale_hits = len([a for a in (account_keys or []) if a in WHALES])
    score += min(whale_hits * 2, 6)  # 0..6
    details["whale_hits"] = whale_hits

    # 2) Unique wallets in tx set
    uniq = len(owners)
    if uniq >= 10: score += 2
    elif uniq >= 5: score += 1
    details["unique_wallets"] = uniq

    # 3) Raydium signal (LP/route programs present)
    if any_raydium_program(account_keys):
        score += 2
        details["raydium"] = True
    else:
        details["raydium"] = False

    # 4) Market signal (Dexscreener)
    ds = get_dex_stats(mint)
    if ds:
        liq = ds.get("liquidity_usd", 0.0)
        vol = ds.get("h24_volume_usd", 0.0)
        tx1 = ds.get("txns_h1", 0)
        details.update(ds)
        if liq >= 30_000: score += 2
        elif liq >= 10_000: score += 1
        if vol >= 50_000: score += 1
        if tx1 >= 50: score += 1

    return score, details

# -----------------------------
# DEDUP / RATE LIMIT
# -----------------------------
SEEN = {}  # mint -> ts
TTL_MIN = 20 * 60  # 20 min dedup

def seen_recent(mint: str) -> bool:
    now = time.time()
    t = SEEN.get(mint)
    if t and now - t < TTL_MIN:
        return True
    SEEN[mint] = now
    # cleanup
    for k in list(SEEN.keys()):
        if now - SEEN[k] > TTL_MIN:
            SEEN.pop(k, None)
    return False

# -----------------------------
# FLASK
# -----------------------------
app = Flask(__name__)

@app.get("/")
def index():
    return jsonify({
        "app": "Cryps Ultra Pilot — Webhook",
        "status": "ok",
        "whales_loaded": len(WHALES),
        "public_url": PUBLIC_BASE_URL or "unset",
    })

def ok():
    return jsonify({"ok": True})

# -----------------------------
# HELIUS WEBHOOK
# -----------------------------
@app.post("/hel-webhook")
def hel_webhook():
    # basic shared-secret
    if request.args.get("secret") != HEL_SECRET:
        abort(403)

    payload = request.get_json(silent=True) or {}
    # enhanced webhook usually: {"type":"...","events":[...]} or list of txns
    events = []
    if isinstance(payload, dict) and "events" in payload:
        events = payload["events"] or []
    elif isinstance(payload, list):
        events = payload
    else:
        # single event?
        events = [payload]

    mints_total = 0
    winners_sent = 0

    for ev in events:
        # Collect addresses present in the transaction
        account_keys = []
        if isinstance(ev, dict):
            account_keys = list(set( (ev.get("accountData", []) or []) + (ev.get("accountKeys", []) or []) ))
            # fallback: some payloads use "accountKeysList"
            if not account_keys and isinstance(ev.get("accountKeysList"), list):
                account_keys = ev["accountKeysList"]

        # Collect mints from tokenTransfers
        token_transfers = ev.get("tokenTransfers", []) if isinstance(ev, dict) else []
        mints = set()
        owners = set()
        for tr in token_transfers:
            m = tr.get("mint") or tr.get("tokenAddress")
            if m:
                mints.add(m)
            if tr.get("fromUserAccount"): owners.add(tr.get("fromUserAccount"))
            if tr.get("toUserAccount"): owners.add(tr.get("toUserAccount"))

        # also capture if "mint" field exists (CREATE/MINT events)
        base_mint = ev.get("mint") or ev.get("tokenAddress")
        if base_mint:
            mints.add(base_mint)

        # No mint found? skip
        if not mints:
            continue

        for mint in mints:
            if seen_recent(mint):
                continue

            mints_total += 1
            score, info = compute_cryps_score(mint, account_keys, owners)

            # Filter: Winners only
            if score < 9:
                # uncomment to debug low-score feed
                # tg_send(f"🐣 Skipped {mint}\nCrypsScore: {score}/12")
                continue

            winners_sent += 1

            # Build message
            solscan_link = SOLSCAN_MINT.format(mint)
            ds_link = info.get("pair_url") or DEXSCREENER.format(mint)

            header = "🏆 <b>Winner Token</b>"
            ray = "yes" if info.get("raydium") else "no"
            whale_hits = info.get("whale_hits", 0)
            uniq = info.get("unique_wallets", 0)

            parts = [
                f"{header}",
                f"<code>{mint}</code>",
                f"Raydium: <b>{ray}</b> | Whales: <b>{whale_hits}</b> | Wallets: <b>{uniq}</b>",
            ]

            liq = info.get("liquidity_usd"); vol = info.get("h24_volume_usd"); tx1 = info.get("txns_h1")
            if liq is not None or vol is not None or tx1 is not None:
                parts.append(
                    f"Liquidity: <b>{human_usd(liq)}</b> | 24h Vol: <b>{human_usd(vol)}</b> | 1h TXs: <b>{tx1}</b>"
                )

            parts.append(f'<a href="{solscan_link}">Solscan</a> | <a href="{ds_link}">DexScreener</a>')
            parts.append(f"CrypsScore: <b>{score}/12</b>")

            tg_send("\n".join(parts), preview=True)

    return jsonify({"ok": True, "mints": mints_total, "winners": winners_sent})

# -----------------------------
# RUN (for local debug)
# -----------------------------
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)
