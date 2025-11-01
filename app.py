if isinstance(data, list):
    txs = data
elif isinstance(data, dict):
    txs = data.get("transactions") ...
    
    expected = HEL_SECRET or ""
    # مصادقة: X-Cryps-Secret أو Authorization: Bearer أو ?secret=
    got = request.headers.get("X-Cryps-Secret") or request.args.get("secret") or ""
    if not got:
        auth = request.headers.get("Authorization", "")
        if auth.lower().startswith("bearer "):
            got = auth.split(" ", 1)[1].strip()
    if got != expected:
        app.logger.warning(f"[HEL] SECRET MISMATCH: got='{got}' expected='{expected}'")
        return ("unauthorized", 403)

    data = request.get_json(silent=True)
    if data is None:
        app.logger.warning("[HEL] No JSON body")
        return jsonify(ok=True), 200

    # ✅ جهّز txs مهما كان شكل البودي
    if isinstance(data, list):
        txs = data
    elif isinstance(data, dict):
        # Helius enhanced غالباً كيبعث 'transactions' أو 'events'
        txs = data.get("transactions") or data.get("events") or []
        # بعض الحالات كيبعث عنصر واحد مباشرة
        if isinstance(txs, dict):
            txs = [txs]
    else:
        txs = []

    if not txs:
        send_tg("⚙️ Test Webhook Received (no transactions)")
        return jsonify(ok=True), 200

    for tx in txs:
        try:
            # خدم ب .get غير إلا كان dict
            tx = tx or {}
            if not isinstance(tx, dict):
                continue

            sig = (
                tx.get("signature")
                or (tx.get("transaction") or {}).get("signature")
                or "unknown"
            )

            # nativeTransfers: يقدر يكون list أو dict أو ماكينش
            native = tx.get("nativeTransfers") or []
            if isinstance(native, dict):
                native = [native]
            lamports = 0
            if native and isinstance(native[0], dict):
                lamports = native[0].get("amount", 0) or native[0].get("lamports", 0) or 0
            sol_value = float(lamports) / 1e9

            # tokenTransfers نفس الشي
            token_mint = "Unknown"
            tts = tx.get("tokenTransfers") or []
            if isinstance(tts, dict):
                tts = [tts]
            if tts and isinstance(tts[0], dict):
                token_mint = tts[0].get("mint") or tts[0].get("tokenAddress") or "Unknown"

            tx_type = (
                tx.get("type")
                or tx.get("activityType")
                or (tx.get("events") or {}).get("type")
                or "UNKNOWN"
            )

            # CrypsScore بسيط
            score = 0
            if sol_value > 5: score += 4
            if tx_type == "TOKEN_MINT": score += 3
            accs = tx.get("accounts") or []
            if isinstance(accs, dict): accs = [accs]
            if isinstance(accs, list) and len(accs) > 10: score += 2
            if tts: score += 1
            score = min(round(score, 1), 10)

            # Alerts
            if sol_value >= 5:
                send_tg(
                    f"🦈 *Whale Detected*\n"
                    f"💰 {sol_value:.2f} SOL\n"
                    f"🔗 [Solscan](https://solscan.io/tx/{sig})\n"
                    f"📊 CrypsScore: *{score}/10*"
                )
            elif tx_type == "TOKEN_MINT":
                send_tg(
                    f"⚡ *New Token Minted*\n"
                    f"🪙 {token_mint}\n"
                    f"🔗 [Solscan](https://solscan.io/token/{token_mint})\n"
                    f"📊 CrypsScore: *{score}/10*"
                )
            elif score >= 7:
                send_tg(
                    f"🚀 *Winner Candidate Found*\n"
                    f"🔗 [Solscan](https://solscan.io/tx/{sig})\n"
                    f"📊 CrypsScore: *{score}/10*"
                )

        except Exception as e:
            app.logger.warning(f"[HEL] tx parse error: {e}")

    return jsonify(ok=True), 200
