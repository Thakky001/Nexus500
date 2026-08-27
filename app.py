from flask import Flask, jsonify, render_template, request
import threading
import os

from config import *
from core.orchestrator import run_scan
from services.sheets import read_sheet_data

app = Flask(__name__)

# ══════════════════════════════════════════════
@app.route("/")
def index():
    """
    หน้าหลัก — Web Dashboard ดึงประวัติจาก Google Sheets
    หากยังไม่ได้ตั้งค่า Google Sheets จะแสดง config เปล่าๆ
    """
    rows   = read_sheet_data(limit=300)
    config = {
        "layer0_fund":   f"ROE>{MIN_ROE*100}%, D/E<{MAX_DEBT_EQUITY}%, Margin>{MIN_PROFIT_MARGIN*100}%",
        "layer1_trend":  "price > EMA20 > EMA50 > EMA200",
        "layer1_slope":  f"EMA50 slope >= {MIN_EMA50_SLOPE}%",
        "layer1_adx":    f">= {MIN_ADX}",
        "layer2_rsi":    f"{RSI_LOW}–{RSI_HIGH}",
        "layer2_macd":   f"histogram > {MIN_MACD_HIST}",
        "layer3_volume": f">= {MIN_AVG_VOLUME/1e6:.0f}M",
        "min_score":     f"{MIN_SCORE}/10",
        "valuation_filter": f"PE<{MAX_PE_RATIO}, PEG<{MAX_PEG_RATIO}",
        "max_per_sector":   f"{MAX_PER_SECTOR} ตัว",
        "stop_loss":        f"EMA200 -{STOP_LOSS_PCT}%",
        "position_size":    f"Max Risk {MAX_RISK_PER_TRADE}% / Max Pos {MAX_POSITION_PCT}%",
    }
    return render_template("dashboard.html", rows=rows, config=config)


@app.route("/api/history")
def api_history():
    """JSON endpoint สำหรับใครต้องการดึงข้อมูลผ่าน API"""
    rows = read_sheet_data(limit=300)
    return jsonify({"status": "ok", "count": len(rows), "data": rows})


@app.route("/trigger")
def trigger():
    missing = [k for k, v in {
        "TELEGRAM_BOT_TOKEN": TELEGRAM_BOT_TOKEN,
        "TELEGRAM_CHAT_ID":   TELEGRAM_CHAT_ID,
        "HF_API_TOKEN":       HF_API_TOKEN,
    }.items() if not v]
    if missing:
        return jsonify({"status": "error", "missing": missing}), 500

    threading.Thread(target=run_scan, daemon=True).start()
    return jsonify({
        "status":  "accepted",
        "message": "LONG-TERM SCANNER (1000 Stocks) เริ่มสแกนแล้ว 🔍",
        "filters": f"Score>={MIN_SCORE} | Fund+Trend+RSI",
    })


@app.route("/health")
def health():
    sheet_ok = bool(GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON)
    return jsonify({
        "status":        "healthy",
        "google_sheets": "configured" if sheet_ok else "not configured",
        "config": {
            "max_position_pct":  MAX_POSITION_PCT,
            "sentiment_mode":    "score_adjustment",
            "macro_indicators":  True,
            "news_sources":      ["Yahoo Finance", "Google News"],
            "weighted_scoring":  True,
        },
    })


@app.route("/backtest")
def backtest():
    """
    Backtesting endpoint — วิเคราะห์ประสิทธิภาพ Signal ย้อนหลัง
    Query params:
      days  : int  จำนวนวันย้อนหลัง (default 90)
    Example: /backtest?days=180
    """
    days = request.args.get('days', 90, type=int)
    days = max(7, min(days, 365))  # คุม range ไว้  7–365 วัน
    try:
        from core.backtest import backtest_signals
        result = backtest_signals(lookback_days=days)
        return jsonify({"status": "ok", **result})
    except Exception as e:
        return jsonify({"status": "error", "message": str(e)}), 500



# ══════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)
