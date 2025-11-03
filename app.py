# app.py
# Cryps Ultra Pilot - Minimal Controlled Mode (no auto schedule)
# Runs manual scans (/scan, /kinchi) + handles Helius webhook events.
# Author: Cryps King

import os
import json
import time
from datetime import datetime
from threading import Thread

from flask import Flask, request, jsonify
import telebot

# ========= ENV VARS =========
BOT_TOKEN = os.getenv("BOT_TOKEN", "")
CHAT_ID = int(os.getenv("CHAT_ID", "0"))           # your Telegram chat id (int)
HEL_SEC = os.getenv("HEL_WEBHOOK_SECRET", "")      # Helius secret to verify webhook
APP_ENV = os.getenv("APP_ENV", "render")           # just info

# ========= BASIC GUARDS =========
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN is missing")
if not CHAT_ID:
    raise RuntimeError("CHAT_ID is missing (must be int)")
if not HEL_SEC:
    raise RuntimeError("HEL_WEBHOOK_SECRET is missing")

# ========= PATHS & FILES =========
DATA_DIR = "data"
WHALES_FILE = os.path.join(DATA_DIR, "whales.txt")
TOKENS_FILE = os.path.join(DATA_DIR, "tokens.json")
LOG_FILE = os.path.join(DATA_DIR, "signals.log")

os.makedirs(DATA_DIR, exist_ok=True)
# create default files if missing
if not os.path.exists(WHALES_FILE):
    with open(WHALES_FILE, "w") as f:
        f.write("")  # empty list initially
if not os.path.exists(TOKENS_FILE):
    with open(TOKENS_FILE, "w") as f:
        json.dump({"winners": []}, f, ensure_ascii=False, indent=2)
if not os.path.exists(LOG_FILE):
    with open(LOG_FILE, "w") as f:
        f.write("")

# ========= TELEGRAM =========
bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

def send_tg(text: str, disable_preview: bool = False):
    try:
        bot.send_message(CHAT_ID, text, disable_web_page_preview=disable_preview)
    except Exception as e:
        print("TG SEND ERR:", e)

# ========= HELPERS =========
def now_utc_iso():
    return datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")

def read_whales() -> set:
    try:
        with open(WHALES_FILE, "r") as f:
            addrs = [ln.strip() for ln in f if ln.strip()]
            return set(addrs)
    except Exception:
        return set()

def save_whales(addrs: set):
    with open(WHALES_FILE, "w") as f:
        for a in sorted(addrs):
            f.write(a + "\n")

def log_signal(line: str):
    with open(LOG_FILE, "a") as log:
        log.write(f"[{now_utc_iso()}] {line}\n")

def ingest_tx(tx: dict) -> dict:
    """
    Normalize Helius 'transaction' object into a simple dict.
    We only pull bits we need: signature, type, mint, accounts, sol amount, etc.
    """
    e = {
        "sig": tx.get("signature") or tx.get("signatureInfo") or "",
        "type": tx.get("type") or "",
        "accounts": [],
        "mint": None,
        "sol": 0.0,
    }

    # accounts list
    accs = tx.get("accounts") or tx.get("accountData") or []
    if isinstance(accs, list):
        e["accounts"] = [a.get("account") if isinstance(a, dict) else str(a) for a in accs]

    # token mint events
    # Helius Enhanced has "tokenTransfers" or "nativeTransfers"
    tts = tx.get("tokenTransfers") or []
    if tts and isinstance(tts, list):
        # take the first mint address if present
        mint = tts[0].get("mint")
        if mint:
            e["mint"] = mint

    # SOL native transfer sum (approx)
    nts = tx.get("nativeTransfers") or []
    total_sol = 0.0
    for t in nts:
        # amount is in lamports; convert to SOL if provided
        amt = t.get("amount", 0)
        # many webhooks send lamports as int; convert to SOL
        try:
            total_sol += float(amt) / 1_000_000_000
        except Exception:
            pass
    e["sol"] = round(total_sol, 4)

    return e

def format_mint_msg(mint: str, score: int = 4):
    sc_line = f"📊 CrypsScore: {score}/10"
    return (
        f"⚡ <b>New Token Minted</b>\n"
        f"<code>{mint}</code>\n"
        f"<a href=\"https://solscan.io/token/{mint}\">Solscan</a> | "
        f"<a href=\"https://dexscreener.com/solana/{mint}\">DexScreener</a>\n"
        f"{sc_line}"
    )

def format_whale_msg(e: dict):
    sig = e.get("sig") or ""
    sol = e.get("sol", 0.0)
    return (
        f"🐳 <b>Whale Detected</b>\n"
        f"{sol} SOL\n"
        f"<a href=\"https://solscan.io/tx/{sig}\">Solscan</a>"
    )

def summarize_feed(n_mints: int, n_whales: int):
    msg = f"🛰️ Feed: {n_mints} mints, {n_whales} whale txs"
    send_tg(msg, disable_preview=True)
    log_signal(msg)
    return msg

def check_mints_and_whales() -> str:
    """
    Manual scan hook (placeholder).
    We only echo last status, because real-time comes from /hel-webhook.
    """
    # Read last log line if exists
    try:
        with open(LOG_FILE, "r") as f:
            lines = f.readlines()
            for ln in reversed(lines):
                if "Feed:" in ln:
                    last = ln.strip().split("] ", 1)[-1]
                    return last
    except Exception:
        pass
    return "Feed: 0 mints, 0 whale txs"

# ========= FLASK APP =========
app = Flask(__name__)

@app.get("/")
def root():
    return jsonify(ok=True, service="Cryps Ultra Pilot", env=APP_ENV, time=now_utc_iso())

@app.get("/healthz")
def healthz():
    return "ok", 200

# ======= HELIUS WEBHOOK =======
@app.post("/hel-webhook")
def hel_webhook():
    secret = request.headers.get("X-Cryps-Secret") or request.args.get("secret")
    if secret != HEL_SEC:
        return jsonify(error="unauthorized"), 403

    try:
        evt = request.get_json(silent=True)
        if not evt:
            return jsonify(error="no_json"), 400

        # enhanced webhook may send {"transactions":[...]}
        txs = evt.get("transactions", [])
        whales = read_whales()
        n_mints = 0
        n_whales = 0

        for tx in txs:
            try:
                e = ingest_tx(tx)

                # decide whale hit: any whale address appears in accounts
                accs = set(e.get("accounts", []))
                if whales and accs and (accs & whales):
                    n_whales += 1
                    send_tg(format_whale_msg(e))

                # mint signal
                if (e.get("type") or "").upper().find("MINT") >= 0 or e.get("mint"):
                    n_mints += 1
                    if e.get("mint"):
                        send_tg(format_mint_msg(e["mint"]))
                    else:
                        send_tg("⚡ New Mint detected")

            except Exception as ex:
                print("ERR loop:", ex)

        # summary once per webhook batch
        summarize_feed(n_mints, n_whales)
        return jsonify(ok=True, parsed=len(txs), mints=n_mints, whales=n_whales), 200

    except Exception as e:
        print("HEL ERR:", e)
        return jsonify(error="server_error"), 500

# ========= TELEGRAM COMMANDS =========
HELP_TEXT = (
    "✅ <b>Cryps Ultra Pilot Online</b>\n"
    "Commands: /scan, /kinchi, /winners, /whales\n"
    "Admin: /whale_add &lt;addr&gt;, /whale_remove &lt;addr&gt;\n"
    "— Live comes from Helius webhook; /scan just shows last feed."
)

@bot.message_handler(commands=["start", "help"])
def cmd_start(msg):
    send_tg(HELP_TEXT, disable_preview=True)

@bot.message_handler(commands=["scan", "kinchi"])
def cmd_scan(msg):
    res = check_mints_and_whales()
    send_tg(res, disable_preview=True)

@bot.message_handler(commands=["winners"])
def cmd_winners(msg):
    try:
        with open(TOKENS_FILE, "r") as f:
            data = json.load(f)
        winners = data.get("winners", [])
        if not winners:
            send_tg("🏆 Top Winner Tokens (24h)\n— module v1.1 coming next.")
            return
        lines = ["🏆 <b>Top Winner Tokens (24h)</b>"]
        for w in winners[:10]:
            mint = w.get("mint", "")
            lines.append(f"• <code>{mint}</code>")
        send_tg("\n".join(lines))
    except Exception as e:
        print("WIN ERR:", e)
        send_tg("🏆 Top Winner Tokens (24h)\n— module v1.1 coming next.")

@bot.message_handler(commands=["whales"])
def cmd_whales(msg):
    wl = list(read_whales())
    if not wl:
        send_tg("Whales List: (empty)")
        return
    txt = ["Whales List:"]
    for i, a in enumerate(wl, 1):
        txt.append(f"{i}. <code>{a}</code>")
    send_tg("\n".join(txt), disable_preview=True)

@bot.message_handler(commands=["whale_add"])
def cmd_whale_add(msg):
    if msg.chat.id != CHAT_ID:
        return
    parts = msg.text.strip().split()
    if len(parts) < 2:
        send_tg("Usage:\n/whale_add <WALLET_ADDRESS>")
        return
    addr = parts[1].strip()
    wl = read_whales()
    wl.add(addr)
    save_whales(wl)
    send_tg("✅ Whale added.\n/whales to view list.", disable_preview=True)

@bot.message_handler(commands=["whale_remove"])
def cmd_whale_rm(msg):
    if msg.chat.id != CHAT_ID:
        return
    parts = msg.text.strip().split()
    if len(parts) < 2:
        send_tg("Usage:\n/whale_remove <WALLET_ADDRESS>")
        return
    addr = parts[1].strip()
    wl = read_whales()
    if addr in wl:
        wl.remove(addr)
        save_whales(wl)
        send_tg("🗑️ Whale removed.", disable_preview=True)
    else:
        send_tg("Address not in list.", disable_preview=True)

# ========= BOT POLLING (single background thread) =========
def _polling():
    # long-polling inside Render web service works fine
    while True:
        try:
            bot.infinity_polling(timeout=30, long_polling_timeout=30)
        except Exception as e:
            print("POLL ERR:", e)
            time.sleep(3)

Thread(target=_polling, daemon=True).start()

# ========= GUNICORN ENTRY =========
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)

