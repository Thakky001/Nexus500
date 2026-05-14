"""
╔══════════════════════════════════════════════════════════╗
║         S&P 500 Stock Scanner Bot  •  app.py             ║
║  Flask + yfinance + pandas-ta + FinBERT + Telegram       ║
╚══════════════════════════════════════════════════════════╝

วิธีตั้งค่า Environment Variables บน Render:
  TELEGRAM_BOT_TOKEN   = token จาก @BotFather
  TELEGRAM_CHAT_ID     = Chat ID ของ Channel (ขึ้นต้นด้วย -100...)
  HF_API_TOKEN         = Hugging Face API Token (จาก hf.co/settings/tokens)
"""

import io
import os
import time
import threading
import logging

import requests
import pandas as pd
import pandas_ta_classic as ta  # เปลี่ยนจาก pandas_ta เป็น pandas_ta_classic
import yfinance as yf
from flask import Flask, jsonify

# ─────────────────────────────────────────────
#  Logging
# ─────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)

# ─────────────────────────────────────────────
#  Config — อ่านจาก Environment Variables
# ─────────────────────────────────────────────
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID   = os.environ.get("TELEGRAM_CHAT_ID", "")
HF_API_TOKEN       = os.environ.get("HF_API_TOKEN", "")

# FinBERT model บน Hugging Face
HF_MODEL_URL = (
    "https://api-inference.huggingface.co/models/ProsusAI/finbert"
)

# พารามิเตอร์คัดกรอง
MIN_VOLUME      = 1_000_000   # วอลุ่มขั้นต่ำ
RSI_LOW         = 45          # RSI ขั้นต่ำ
RSI_HIGH        = 65          # RSI สูงสุด
CHUNK_SIZE      = 50          # ดึงข้อมูลทีละกี่ตัว
CHUNK_PAUSE     = 10          # พักกี่วินาทีระหว่าง chunk
NEWS_PAUSE      = 5           # พักกี่วินาทีระหว่างดึงข่าวแต่ละตัว
AI_PAUSE        = 20          # พักกี่วินาทีระหว่างส่ง AI แต่ละตัว
AI_RETRY_WAIT   = 30          # รอกี่วินาทีเมื่อโดน 429

# ─────────────────────────────────────────────
#  Flask App
# ─────────────────────────────────────────────
app = Flask(__name__)


# ══════════════════════════════════════════════
#  STEP 1 — โหลดรายชื่อ S&P 500 จาก Wikipedia
# ══════════════════════════════════════════════
def get_sp500_tickers() -> list[str]:
    """ดึงรายชื่อหุ้น S&P 500 ทั้งหมดจาก Wikipedia"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/124.0.0.0 Safari/537.36"
        )
    }
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), attrs={"id": "constituents"})
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        log.info(f"โหลดรายชื่อหุ้นสำเร็จ: {len(tickers)} ตัว")
        return tickers
    except Exception as e:
        log.error(f"โหลดรายชื่อหุ้นล้มเหลว: {e}")
        return []


# ══════════════════════════════════════════════
#  STEP 2 — ดึงข้อมูลกราฟและคัดกรองทางเทคนิค
# ══════════════════════════════════════════════
def fetch_and_filter(tickers: list[str]) -> list[dict]:
    """
    ดึงกราฟย้อนหลัง 1 ปี ทีละ CHUNK_SIZE ตัว
    แล้วคัดเฉพาะหุ้นที่:
      - Volume เฉลี่ย 20 วัน > 1 ล้าน
      - ราคา > EMA50 > EMA200
      - RSI อยู่ระหว่าง 45–65
    """
    passed = []
    chunks = [tickers[i : i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]

    for idx, chunk in enumerate(chunks, start=1):
        log.info(f"กำลังโหลด chunk {idx}/{len(chunks)} ({len(chunk)} ตัว)...")
        try:
            raw = yf.download(
                tickers=chunk,
                period="1y",
                interval="1d",
                group_by="ticker",
                auto_adjust=True,
                progress=False,
                threads=False,
            )
        except Exception as e:
            log.warning(f"ดาวน์โหลด chunk {idx} ล้มเหลว: {e}")
            time.sleep(CHUNK_PAUSE)
            continue

        for ticker in chunk:
            try:
                # yfinance v1.x: multi-ticker → columns are (field, ticker)
                # single ticker → columns are flat (Close, Volume, ...)
                if len(chunk) == 1:
                    df = raw.copy()
                else:
                    if not hasattr(raw.columns, "levels"):
                        continue
                    lvl0 = raw.columns.get_level_values(0).unique().tolist()
                    lvl1 = raw.columns.get_level_values(1).unique().tolist()
                    if ticker in lvl1:
                        df = raw.xs(ticker, axis=1, level=1).copy()
                    elif ticker in lvl0:
                        df = raw[ticker].copy()
                    else:
                        continue

                df.dropna(subset=["Close", "Volume"], inplace=True)
                if len(df) < 210:          # ต้องการข้อมูลพอคำนวณ EMA200
                    continue

                # ─── คำนวณ Indicators ───
                close = df["Close"]
                df["ema50"]  = ta.ema(close, length=50)
                df["ema200"] = ta.ema(close, length=200)
                df["rsi"]    = ta.rsi(close, length=14)

                last = df.iloc[-1]
                avg_vol = df["Volume"].tail(20).mean()

                # ─── เกณฑ์คัดกรอง ───
                price   = float(last["Close"])
                ema50   = float(last["ema50"])
                ema200  = float(last["ema200"])
                rsi_val = float(last["rsi"])

                if (
                    avg_vol > MIN_VOLUME
                    and price > ema50 > ema200
                    and RSI_LOW <= rsi_val <= RSI_HIGH
                ):
                    passed.append(
                        {
                            "ticker":  ticker,
                            "price":   round(price, 2),
                            "ema50":   round(ema50, 2),
                            "ema200":  round(ema200, 2),
                            "rsi":     round(rsi_val, 2),
                            "avg_vol": int(avg_vol),
                        }
                    )
                    log.info(f"  ✅ {ticker} ผ่านเกณฑ์ — Price:{price:.2f} EMA50:{ema50:.2f} RSI:{rsi_val:.1f}")

            except Exception as e:
                log.debug(f"  ❌ {ticker}: {e}")

        # พักระหว่าง chunk (ยกเว้น chunk สุดท้าย)
        if idx < len(chunks):
            log.info(f"พัก {CHUNK_PAUSE} วินาที...")
            time.sleep(CHUNK_PAUSE)

    log.info(f"ผ่านเกณฑ์กราฟทั้งหมด: {len(passed)} ตัว")
    return passed


# ══════════════════════════════════════════════
#  STEP 3 — ดึงข่าวล่าสุดผ่าน Yahoo Finance RSS
# ══════════════════════════════════════════════
def fetch_news(ticker: str, max_items: int = 3) -> list[str]:
    """ดึงหัวข้อข่าวล่าสุดจาก Yahoo Finance RSS"""
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    headlines = []
    try:
        resp = requests.get(url, timeout=10,
                            headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        # parse XML อย่างง่ายด้วย lxml ผ่าน pandas read_xml
        from lxml import etree
        root = etree.fromstring(resp.content)
        items = root.findall(".//item/title")
        for item in items[:max_items]:
            if item.text:
                headlines.append(item.text.strip())
    except Exception as e:
        log.debug(f"ดึงข่าว {ticker} ล้มเหลว: {e}")
    return headlines


# ══════════════════════════════════════════════
#  STEP 4 — วิเคราะห์ Sentiment ด้วย FinBERT
# ══════════════════════════════════════════════
def analyze_sentiment(headlines: list[str]) -> str:
    """
    ส่งหัวข้อข่าวไปให้ FinBERT บน Hugging Face
    คืนค่า: "positive" | "negative" | "neutral" | "error"
    """
    if not headlines:
        return "neutral"

    text = ". ".join(headlines)
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}

    for attempt in range(3):
        try:
            resp = requests.post(
                HF_MODEL_URL, headers=headers, json=payload, timeout=30
            )
            if resp.status_code == 429:
                log.warning(f"FinBERT 429 — รอ {AI_RETRY_WAIT} วินาที (attempt {attempt+1})")
                time.sleep(AI_RETRY_WAIT)
                continue
            resp.raise_for_status()
            result = resp.json()

            # FinBERT คืนค่าเป็น list ของ list ของ dict
            # [[ {"label": "positive", "score": 0.9}, ... ]]
            if isinstance(result, list) and result:
                inner = result[0]
                if isinstance(inner, list):
                    best = max(inner, key=lambda x: x.get("score", 0))
                    return best.get("label", "neutral").lower()
                elif isinstance(inner, dict):
                    return inner.get("label", "neutral").lower()

        except Exception as e:
            log.warning(f"FinBERT error (attempt {attempt+1}): {e}")
            time.sleep(AI_RETRY_WAIT)

    return "error"


# ══════════════════════════════════════════════
#  STEP 5 — ส่งข้อความเข้า Telegram
# ══════════════════════════════════════════════
def send_telegram(message: str) -> bool:
    """ส่งข้อความ Markdown v2 ไปยัง Telegram Channel"""
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f"ส่ง Telegram ล้มเหลว: {e}")
        return False


def format_volume(vol: int) -> str:
    if vol >= 1_000_000_000:
        return f"{vol/1_000_000_000:.1f}B"
    if vol >= 1_000_000:
        return f"{vol/1_000_000:.1f}M"
    return f"{vol:,}"


def build_message(stock: dict, headlines: list[str]) -> str:
    """สร้างข้อความแจ้งเตือนสวยงาม"""
    ticker   = stock["ticker"]
    price    = stock["price"]
    ema50    = stock["ema50"]
    ema200   = stock["ema200"]
    rsi      = stock["rsi"]
    avg_vol  = format_volume(stock["avg_vol"])

    news_lines = ""
    for i, h in enumerate(headlines, 1):
        news_lines += f"  {i}. {h}\n"

    msg = (
        f"📈 <b>${ticker}</b>  •  S&amp;P 500 Scanner\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"💲 <b>ราคา:</b>  ${price:,.2f}\n"
        f"📊 <b>EMA 50:</b>  ${ema50:,.2f}\n"
        f"📊 <b>EMA 200:</b>  ${ema200:,.2f}\n"
        f"🔢 <b>RSI (14):</b>  {rsi}\n"
        f"📦 <b>Vol เฉลี่ย:</b>  {avg_vol}\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 <b>ข่าวล่าสุด (Sentiment: 🟢 Positive)</b>\n"
        f"{news_lines}"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"⚠️ <i>ข้อมูลนี้เพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำการลงทุน</i>"
    )
    return msg


# ══════════════════════════════════════════════
#  งานหลัก — รันใน Background Thread
# ══════════════════════════════════════════════
def run_scan():
    """ฟังก์ชันสแกนหุ้นทั้งหมด รันเบื้องหลัง"""
    log.info("═══════════════════════════════")
    log.info("  เริ่มต้นสแกน S&P 500 Bot")
    log.info("═══════════════════════════════")

    # ── Phase 1: โหลดรายชื่อ ──
    tickers = get_sp500_tickers()
    if not tickers:
        log.error("ไม่มีรายชื่อหุ้น หยุดทำงาน")
        return

    # ── Phase 2: คัดกรองทางเทคนิค ──
    candidates = fetch_and_filter(tickers)
    if not candidates:
        log.info("ไม่มีหุ้นผ่านเกณฑ์ในวันนี้")
        send_telegram("🔍 <b>S&P 500 Scanner</b>\n\nไม่มีหุ้นผ่านเกณฑ์ทางเทคนิคในวันนี้ 📭")
        return

    # ── Phase 3+4: ดึงข่าว + วิเคราะห์ AI ──
    positive_results = []

    for stock in candidates:
        ticker = stock["ticker"]
        log.info(f"กำลังดึงข่าว {ticker}...")
        time.sleep(NEWS_PAUSE)

        headlines = fetch_news(ticker)
        if not headlines:
            log.info(f"  {ticker}: ไม่มีข่าว → ข้าม")
            continue

        log.info(f"  {ticker}: ส่ง FinBERT วิเคราะห์ {len(headlines)} ข่าว...")
        time.sleep(AI_PAUSE)

        sentiment = analyze_sentiment(headlines)
        log.info(f"  {ticker}: Sentiment = {sentiment}")

        if sentiment == "positive":
            positive_results.append((stock, headlines))

    # ── Phase 5: ส่งเข้า Telegram ──
    if not positive_results:
        log.info("ไม่มีหุ้นที่ข่าว Positive")
        send_telegram("🔍 <b>S&P 500 Scanner</b>\n\nผ่านเกณฑ์กราฟ แต่ไม่มีข่าว Positive วันนี้ 📭")
        return

    # ส่งหัวข้อสรุปก่อน
    summary = (
        f"🚨 <b>S&P 500 Daily Scan</b> 🚨\n"
        f"พบหุ้นน่าสนใจ <b>{len(positive_results)} ตัว</b> "
        f"(จาก {len(candidates)} ตัวที่ผ่านเกณฑ์กราฟ)\n"
        f"━━━━━━━━━━━━━━━━━━━━"
    )
    send_telegram(summary)
    time.sleep(2)

    for stock, headlines in positive_results:
        msg = build_message(stock, headlines)
        success = send_telegram(msg)
        log.info(f"ส่ง {stock['ticker']} → {'✅' if success else '❌'}")
        time.sleep(3)

    log.info("═══════════════════════════════")
    log.info(f"  เสร็จสิ้น! ส่ง {len(positive_results)} ตัว")
    log.info("═══════════════════════════════")


# ══════════════════════════════════════════════
#  Flask Routes
# ══════════════════════════════════════════════
@app.route("/")
def index():
    return jsonify({"status": "ok", "message": "S&P 500 Bot is running 🚀"})


@app.route("/trigger")
def trigger():
    """
    Endpoint ที่ cron-job.org จะเรียกทุกวัน
    ตอบกลับทันที แล้วโยนงานไปทำ Background
    """
    # ตรวจสอบ config เบื้องต้น
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID or not HF_API_TOKEN:
        missing = []
        if not TELEGRAM_BOT_TOKEN: missing.append("TELEGRAM_BOT_TOKEN")
        if not TELEGRAM_CHAT_ID:   missing.append("TELEGRAM_CHAT_ID")
        if not HF_API_TOKEN:       missing.append("HF_API_TOKEN")
        return jsonify({
            "status": "error",
            "message": f"Environment variables ขาด: {', '.join(missing)}"
        }), 500

    thread = threading.Thread(target=run_scan, daemon=True)
    thread.start()

    return jsonify({
        "status": "accepted",
        "message": "เริ่มสแกนแล้ว! ผลจะส่งเข้า Telegram เมื่อเสร็จ 🔍"
    })


@app.route("/health")
def health():
    """Health check สำหรับ Render"""
    return jsonify({"status": "healthy"})


# ══════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)