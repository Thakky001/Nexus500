"""
╔══════════════════════════════════════════════════════════╗
║   S&P 500 Stock Scanner Bot  •  app.py  [LONG-TERM]      ║
║  Flask + yfinance + pandas-ta + FinBERT + Telegram       ║
║  + Google Sheets History + Web Dashboard                 ║
╠══════════════════════════════════════════════════════════╣
║  ระบบคัดกรอง 4 ชั้น สำหรับการลงทุนระยะยาว / DCA สะสมหุ้น      ║
║  เน้นหุ้นพื้นฐานดีที่ยืนบนแนวโน้มขาขึ้น และรอรับเมื่อราคาย่อตัว      ║
╚══════════════════════════════════════════════════════════╝

Environment Variables บน Render:
  TELEGRAM_BOT_TOKEN        = token จาก @BotFather
  TELEGRAM_CHAT_ID          = Chat ID ของ Channel (ขึ้นต้นด้วย -100...)
  HF_API_TOKEN              = Hugging Face API Token
  GOOGLE_SHEET_ID           = ID ของ Google Sheet (จาก URL)
  GOOGLE_SERVICE_ACCOUNT_JSON = JSON ทั้งหมดของ Service Account (inline string)
"""

import io
import os
import json
import time
import threading
import logging
from datetime import datetime, timezone

import requests
import pandas as pd
import pandas_ta_classic as ta
import yfinance as yf
from flask import Flask, jsonify, render_template_string

# Google Sheets
import gspread
from google.oauth2.service_account import Credentials

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
TELEGRAM_BOT_TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID            = os.environ.get("TELEGRAM_CHAT_ID", "")
HF_API_TOKEN                = os.environ.get("HF_API_TOKEN", "")
GOOGLE_SHEET_ID             = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")

HF_MODEL_URL = "https://router.huggingface.co/hf-inference/models/ProsusAI/finbert"

# ══════════════════════════════════════════════
#  ⚙️  เกณฑ์คัดกรอง (ปรับสำหรับลงทุนระยะยาว)
# ══════════════════════════════════════════════

# ── ชั้น 1: Trend Alignment (บังคับ) ──
MIN_ADX           = 20
EMA_SLOPE_DAYS    = 20
MIN_EMA50_SLOPE   = 0.0

# ── ชั้น 2: Momentum (บังคับ) ─────────
RSI_LOW           = 40
RSI_HIGH          = 70
MIN_MACD_HIST     = -0.5

# ── ชั้น 3: Volume Quality (บังคับ) ─────────
MIN_AVG_VOLUME    = 2_000_000
MIN_VOL_SURGE     = 0.0

# ── ชั้น 4: Price Structure (เพิ่มคะแนน) ────
MAX_PCT_FROM_52W  = 20.0
MIN_5D_MOMENTUM   = -5.0

# ── Scoring ──
MIN_SCORE         = 6
TOP_N             = 5

# ── Rate Limit Protection ────────────────────
CHUNK_SIZE        = 50
CHUNK_PAUSE       = 10
NEWS_PAUSE        = 5
AI_PAUSE          = 20
AI_RETRY_WAIT     = 60

# ─────────────────────────────────────────────
app = Flask(__name__)


# ══════════════════════════════════════════════
#  Google Sheets Helper
# ══════════════════════════════════════════════
SHEET_HEADERS = [
    "date", "ticker", "rank",
    "price", "ema20", "ema50", "ema200",
    "rsi", "adx", "macd_hist",
    "pct_from_52w", "momentum_5d",
    "avg_vol", "vol_surge",
    "score", "sentiment", "confidence",
    "composite",
    "entry_current", "entry_ema50", "entry_ema200",
    "headlines",
    "current_price", "change_pct",
]

def get_gsheet():
    """เปิด Google Sheet และคืน worksheet หลัก"""
    if not GOOGLE_SERVICE_ACCOUNT_JSON or not GOOGLE_SHEET_ID:
        log.warning("Google Sheets ไม่ได้ตั้งค่า — ข้าม")
        return None
    try:
        creds_dict = json.loads(GOOGLE_SERVICE_ACCOUNT_JSON)
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
        gc    = gspread.authorize(creds)
        sh    = gc.open_by_key(GOOGLE_SHEET_ID)

        # ใช้ sheet ชื่อ "ScanHistory" ถ้ายังไม่มีให้สร้างใหม่
        try:
            ws = sh.worksheet("ScanHistory")
            # ตรวจสอบว่า header ครบหรือยัง ถ้าไม่ครบให้เพิ่มอัตโนมัติ
            existing_headers = ws.row_values(1)
            for col_name in SHEET_HEADERS:
                if col_name not in existing_headers:
                    next_col = len(existing_headers) + 1
                    ws.update_cell(1, next_col, col_name)
                    existing_headers.append(col_name)
                    log.info(f"เพิ่ม header '{col_name}' ที่คอลัมน์ {next_col}")
        except gspread.exceptions.WorksheetNotFound:
            ws = sh.add_worksheet(title="ScanHistory", rows=5000, cols=len(SHEET_HEADERS))
            ws.append_row(SHEET_HEADERS)
            log.info("สร้าง worksheet ScanHistory ใหม่")

        return ws
    except Exception as e:
        log.error(f"เชื่อม Google Sheets ล้มเหลว: {e}")
        return None


def save_to_sheet(results: list, scan_date: str):
    """
    บันทึก Top N ลง Google Sheets
    results = list of (stock_dict, headlines_list, confidence_float, composite_float)
    """
    ws = get_gsheet()
    if ws is None:
        return

    rows = []
    for rank, (stock, headlines, confidence, composite) in enumerate(results, 1):
        rows.append([
            scan_date,
            stock["ticker"],
            rank,
            stock.get("price", ""),
            stock.get("ema20", ""),
            stock.get("ema50", ""),
            stock.get("ema200", ""),
            stock.get("rsi", ""),
            stock.get("adx", ""),
            stock.get("macd_hist", ""),
            stock.get("pct_from_52w", ""),
            stock.get("momentum_5d", ""),
            stock.get("avg_vol", ""),
            stock.get("vol_surge", ""),
            stock.get("score", ""),
            "positive",
            round(confidence, 4),
            round(composite, 4),
            stock.get("entry_current", ""),
            stock.get("entry_ema50", ""),
            stock.get("entry_ema200", ""),
            " | ".join(headlines),
            # current_price: ดึงราคาปัจจุบันจาก Google Finance (column B = ticker)
            '=IFERROR(GOOGLEFINANCE(INDIRECT("B"&ROW()),"price"),"")',
            # change_pct: % เปลี่ยนแปลงจากราคาตอนสแกน (column D = price, W = current_price)
            '=IFERROR((INDIRECT("W"&ROW())-INDIRECT("D"&ROW()))/INDIRECT("D"&ROW())*100,"")',
        ])

    try:
        ws.append_rows(rows, value_input_option="USER_ENTERED")
        log.info(f"บันทึก {len(rows)} แถวลง Google Sheets สำเร็จ")
    except Exception as e:
        log.error(f"บันทึก Google Sheets ล้มเหลว: {e}")


def read_sheet_data(limit: int = 200) -> list:
    """
    อ่านข้อมูลย้อนหลังจาก Google Sheets
    คืน list of dict (ล่าสุดก่อน)
    """
    ws = get_gsheet()
    if ws is None:
        return []
    try:
        all_rows = ws.get_all_records()
        # เรียงวันที่ล่าสุดก่อน แต่ภายในวันเดียวกันให้เรียง rank 1→5
        all_rows.sort(key=lambda r: (r.get("date", ""), int(r.get("rank", 99))), reverse=False)
        # แยกกลุ่มวันแล้ว reverse เฉพาะลำดับวัน (ล่าสุดขึ้นก่อน) โดยคง rank ไว้
        dates_seen = []
        for r in all_rows:
            d = r.get("date", "")
            if d not in dates_seen:
                dates_seen.append(d)
        dates_seen.reverse()  # วันล่าสุดก่อน
        date_order = {d: i for i, d in enumerate(dates_seen)}
        all_rows.sort(key=lambda r: (date_order.get(r.get("date", ""), 999), int(r.get("rank", 99))))
        return all_rows[:limit]
    except Exception as e:
        log.error(f"อ่าน Google Sheets ล้มเหลว: {e}")
        return []


# ══════════════════════════════════════════════
#  STEP 1 — โหลดรายชื่อ S&P 500
# ══════════════════════════════════════════════
def get_sp500_tickers() -> list:
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables  = pd.read_html(io.StringIO(resp.text), attrs={"id": "constituents"})
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        log.info(f"โหลดรายชื่อหุ้นสำเร็จ: {len(tickers)} ตัว")
        return tickers
    except Exception as e:
        log.error(f"โหลดรายชื่อหุ้นล้มเหลว: {e}")
        return []


# ══════════════════════════════════════════════
#  STEP 2 — คัดกรอง 4 ชั้น + Scoring
# ══════════════════════════════════════════════
def score_stock(df: pd.DataFrame) -> tuple:
    score   = 0
    details = {}

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]
    last   = df.iloc[-1]

    ema20    = ta.ema(close, length=20)
    ema50    = ta.ema(close, length=50)
    ema200   = ta.ema(close, length=200)
    rsi      = ta.rsi(close, length=14)
    macd_df  = ta.macd(close, fast=12, slow=26, signal=9)
    adx_df   = ta.adx(high, low, close, length=14)

    price      = float(last["Close"])
    e20        = float(ema20.iloc[-1])
    e50        = float(ema50.iloc[-1])
    e200       = float(ema200.iloc[-1])
    rsi_val    = float(rsi.iloc[-1])
    avg_vol_20 = float(volume.tail(20).mean())
    today_vol  = float(last["Volume"])
    high_52w   = float(high.tail(252).max())
    price_5d   = float(close.iloc[-6])

    try:
        hist_col  = [c for c in macd_df.columns if c.startswith("MACDh")][0]
        line_col  = [c for c in macd_df.columns if c.startswith("MACD_")][0]
        sig_col   = [c for c in macd_df.columns if c.startswith("MACDs")][0]
        macd_hist = float(macd_df[hist_col].iloc[-1])
        macd_line = float(macd_df[line_col].iloc[-1])
        macd_sig  = float(macd_df[sig_col].iloc[-1])
    except Exception:
        macd_hist = macd_line = macd_sig = 0.0

    try:
        adx_col = [c for c in adx_df.columns if c.startswith("ADX")][0]
        adx_val = float(adx_df[adx_col].iloc[-1])
    except Exception:
        adx_val = 0.0

    e50_past      = float(ema50.iloc[-1 - EMA_SLOPE_DAYS])
    e50_slope_pct = ((e50 - e50_past) / e50_past * 100) if e50_past > 0 else 0.0

    pct_from_52w = ((high_52w - price) / high_52w * 100) if high_52w > 0 else 999.0
    momentum_5d  = ((price - price_5d) / price_5d * 100) if price_5d > 0 else 0.0
    vol_surge    = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0.0

    entry_current = price
    entry_ema50   = round(e50, 2)
    entry_ema200  = round(e200, 2)

    details.update({
        "price": round(price, 2),       "ema20": round(e20, 2),
        "ema50": round(e50, 2),          "ema200": round(e200, 2),
        "rsi": round(rsi_val, 1),        "macd_hist": round(macd_hist, 4),
        "macd_line": round(macd_line, 4),"macd_sig": round(macd_sig, 4),
        "adx": round(adx_val, 1),        "e50_slope_pct": round(e50_slope_pct, 2),
        "pct_from_52w": round(pct_from_52w, 1), "momentum_5d": round(momentum_5d, 2),
        "avg_vol": int(avg_vol_20),      "vol_surge": round(vol_surge, 2),
        "entry_current": entry_current,  "entry_ema50": entry_ema50,
        "entry_ema200": entry_ema200,
    })

    # ชั้น 1 — Trend
    if not (price > e20 > e50 > e200):
        details["fail"] = "EMA Stack ไม่ครบ"; return -1, details
    if e50_slope_pct < MIN_EMA50_SLOPE:
        details["fail"] = f"EMA50 Slope ต่ำ ({e50_slope_pct:.2f}%)"; return -1, details
    if adx_val < MIN_ADX:
        details["fail"] = f"ADX ต่ำ ({adx_val:.1f})"; return -1, details
    score += 2
    if adx_val >= 30:
        score += 1; details["bonus_adx"] = True

    # ชั้น 2 — Momentum
    if not (RSI_LOW <= rsi_val <= RSI_HIGH):
        details["fail"] = f"RSI ออกนอก Zone ({rsi_val:.1f})"; return -1, details
    if macd_hist <= MIN_MACD_HIST:
        details["fail"] = f"MACD Hist ต่ำ ({macd_hist:.4f})"; return -1, details
    score += 2
    if 40 <= rsi_val <= 55:
        score += 1; details["bonus_rsi"] = True

    # ชั้น 3 — Volume
    if avg_vol_20 < MIN_AVG_VOLUME:
        details["fail"] = f"Volume ต่ำ ({avg_vol_20/1e6:.1f}M)"; return -1, details
    score += 2
    if vol_surge >= 1.5:
        score += 1; details["bonus_vol_surge"] = True

    # ชั้น 4 — Price Structure
    if pct_from_52w <= MAX_PCT_FROM_52W:
        score += 1; details["pass_52w"] = True
    if momentum_5d >= MIN_5D_MOMENTUM:
        score += 1; details["pass_5d_mom"] = True

    return score, details


def fetch_and_filter(tickers: list) -> list:
    passed = []
    chunks = [tickers[i: i + CHUNK_SIZE] for i in range(0, len(tickers), CHUNK_SIZE)]

    for idx, chunk in enumerate(chunks, start=1):
        log.info(f"โหลด chunk {idx}/{len(chunks)} ({len(chunk)} ตัว)...")
        try:
            raw = yf.download(
                tickers=chunk, period="1y", interval="1d",
                group_by="ticker", auto_adjust=True,
                progress=False, threads=False,
            )
        except Exception as e:
            log.warning(f"ดาวน์โหลด chunk {idx} ล้มเหลว: {e}")
            time.sleep(CHUNK_PAUSE)
            continue

        for ticker in chunk:
            try:
                if len(chunk) == 1:
                    df = raw.copy()
                else:
                    if not hasattr(raw.columns, "levels"):
                        continue
                    lvl1 = raw.columns.get_level_values(1).unique().tolist()
                    lvl0 = raw.columns.get_level_values(0).unique().tolist()
                    if ticker in lvl1:
                        df = raw.xs(ticker, axis=1, level=1).copy()
                    elif ticker in lvl0:
                        df = raw[ticker].copy()
                    else:
                        continue

                df.dropna(subset=["Close", "Volume", "High", "Low"], inplace=True)
                if len(df) < 215:
                    continue

                score, details = score_stock(df)

                if score >= MIN_SCORE:
                    passed.append({"ticker": ticker, "score": score, **details})
                    log.info(
                        f"  ✅ {ticker} Score:{score}/10 | "
                        f"RSI:{details['rsi']} ADX:{details['adx']} "
                        f"MACDh:{details['macd_hist']} 5dM:{details['momentum_5d']}%"
                    )
                elif score == -1:
                    log.debug(f"  ❌ {ticker} — {details.get('fail','?')}")
                else:
                    log.debug(f"  ⚠️ {ticker} Score:{score} (ต่ำกว่า {MIN_SCORE})")

            except Exception as e:
                log.debug(f"  ❌ {ticker}: {e}")

        if idx < len(chunks):
            log.info(f"พัก {CHUNK_PAUSE}s...")
            time.sleep(CHUNK_PAUSE)

    passed.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"ผ่านเกณฑ์ทั้งหมด: {len(passed)} ตัว (Score >= {MIN_SCORE})")
    return passed


# ══════════════════════════════════════════════
#  STEP 3 — ดึงข่าว Yahoo Finance RSS
# ══════════════════════════════════════════════
def fetch_news(ticker: str, max_items: int = 3) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    headlines = []
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        from lxml import etree
        root  = etree.fromstring(resp.content)
        items = root.findall(".//item/title")
        for item in items[:max_items]:
            if item.text:
                headlines.append(item.text.strip())
    except Exception as e:
        log.debug(f"ดึงข่าว {ticker} ล้มเหลว: {e}")
    return headlines


# ══════════════════════════════════════════════
#  STEP 4 — FinBERT Sentiment + Confidence
# ══════════════════════════════════════════════
def analyze_sentiment(headlines: list) -> tuple:
    if not headlines:
        return "neutral", 0.0

    text    = ". ".join(headlines)
    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    payload = {"inputs": text}

    for attempt in range(3):
        try:
            resp = requests.post(HF_MODEL_URL, headers=headers, json=payload, timeout=90)
            if resp.status_code == 429:
                log.warning(f"FinBERT 429 — รอ {AI_RETRY_WAIT}s (attempt {attempt+1})")
                time.sleep(AI_RETRY_WAIT)
                continue
            resp.raise_for_status()
            result = resp.json()
            if isinstance(result, list) and result:
                inner = result[0]
                if isinstance(inner, list):
                    best = max(inner, key=lambda x: x.get("score", 0))
                    return best.get("label", "neutral").lower(), best.get("score", 0.0)
                elif isinstance(inner, dict):
                    return inner.get("label", "neutral").lower(), inner.get("score", 0.0)
        except Exception as e:
            log.warning(f"FinBERT error (attempt {attempt+1}): {e}")
            time.sleep(AI_RETRY_WAIT)

    return "error", 0.0


# ══════════════════════════════════════════════
#  STEP 5 — สร้างข้อความ + ส่ง Telegram
# ══════════════════════════════════════════════
def send_telegram(message: str) -> bool:
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID, "text": message,
        "parse_mode": "HTML", "disable_web_page_preview": True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f"ส่ง Telegram ล้มเหลว: {e}")
        return False


def fmt_vol(vol: int) -> str:
    if vol >= 1_000_000_000: return f"{vol/1_000_000_000:.1f}B"
    if vol >= 1_000_000:     return f"{vol/1_000_000:.1f}M"
    return f"{vol:,}"


def score_bar(score: int) -> str:
    return f"{'█' * score}{'░' * (10 - score)} {score}/10"


def build_message(stock: dict, headlines: list, confidence: float, rank: int = 0) -> str:
    s   = stock["score"]
    t   = stock["ticker"]
    bar = score_bar(s)

    rank_label = f"  #{rank} TODAY'S TOP" if rank else ""

    if s >= 9:   badge = f"🏆 ELITE{rank_label}"
    elif s >= 8: badge = f"🥇 STRONG{rank_label}"
    elif s >= 7: badge = f"🥈 GOOD{rank_label}"
    else:        badge = f"🥉 WATCH{rank_label}"

    bonuses = []
    if stock.get("bonus_adx"):       bonuses.append("⚡ ADX มีเทรนด์แข็งแกร่ง")
    if stock.get("bonus_rsi"):       bonuses.append("🎯 RSI โซนเก็บของ")
    if stock.get("bonus_vol_surge"): bonuses.append("📣 มีแรงซื้อผิดปกติ")
    if stock.get("pass_52w"):        bonuses.append("🏔 โครงสร้างราคายกตัว")
    bonus_line = "  ".join(bonuses) if bonuses else "—"

    news_lines = "".join(f"  {i}. {h}\n" for i, h in enumerate(headlines, 1))
    conf_pct   = f"{confidence*100:.0f}%"
    composite  = round(stock["score"] + confidence, 2)

    ecurrent = stock["entry_current"]
    e50      = stock["entry_ema50"]
    e200     = stock["entry_ema200"]

    return (
        f"📈 <b>${t}</b>  {badge} (Long-term)\n"
        f"<code>{bar}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💲 <b>ราคาปัจจุบัน</b>  ${stock['price']:,.2f}\n"
        f"📊 <b>EMA 20/50/200</b>  "
        f"${stock['ema20']:,.2f} / ${stock['ema50']:,.2f} / ${stock['ema200']:,.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 <b>RSI (14)</b>     {stock['rsi']}\n"
        f"📉 <b>MACD Hist</b>   {stock['macd_hist']:+.4f}\n"
        f"🏔 <b>ห่าง 52W High</b> -{stock['pct_from_52w']:.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>แผนการสะสม (Accumulation Zones)</b>\n\n"
        f"  ▶️ <b>ไม้แรก (ราคาปัจจุบัน)</b> : <code>${ecurrent:,.2f}</code>\n"
        f"  ▶️ <b>รอรับย่อ (EMA50)</b>     : <code>${e50:,.2f}</code>\n"
        f"  ▶️ <b>ไม้เผื่อ Panic (EMA200)</b>: <code>${e200:,.2f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ <b>Signals:</b> {bonus_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 <b>ข่าว (🟢 Positive {conf_pct})</b>\n"
        f"{news_lines}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <b>Composite Score</b>: {composite:.2f}  "
        f"<i>(Tech {stock['score']}/10 + Sentiment {conf_pct})</i>\n"
    )


# ══════════════════════════════════════════════
#  งานหลัก — Background Thread
# ══════════════════════════════════════════════
def run_scan():
    log.info("══════════════════════════════════════════")
    log.info("  S&P 500 LONG-TERM SCANNER เริ่มงาน")
    log.info(f"  Score>={MIN_SCORE} | ADX>{MIN_ADX} | RSI {RSI_LOW}–{RSI_HIGH}")
    log.info(f"  Vol>{MIN_AVG_VOLUME/1e6:.0f}M | MACD Hist>{MIN_MACD_HIST} | Full EMA Stack")
    log.info("══════════════════════════════════════════")

    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    tickers = get_sp500_tickers()
    if not tickers:
        return

    candidates = fetch_and_filter(tickers)
    if not candidates:
        send_telegram(
            f"🔍 <b>S&P 500 Long-Term Scanner</b>\n\n"
            f"ไม่มีหุ้นผ่านเกณฑ์ 4 ชั้นวันนี้ 📭\n"
            f"<i>(เกณฑ์: Score >= {MIN_SCORE}/10)</i>"
        )
        return

    positive_results = []
    for stock in candidates:
        ticker = stock["ticker"]
        log.info(f"ดึงข่าว {ticker} (Score:{stock['score']})...")
        time.sleep(NEWS_PAUSE)

        headlines = fetch_news(ticker)
        if not headlines:
            log.info(f"  {ticker}: ไม่มีข่าว → ข้าม")
            continue

        log.info(f"  {ticker}: ส่ง FinBERT ({len(headlines)} ข่าว)...")
        time.sleep(AI_PAUSE)

        label, confidence = analyze_sentiment(headlines)
        log.info(f"  {ticker}: {label} ({confidence*100:.0f}%)")

        if label == "positive":
            composite = stock["score"] + confidence
            positive_results.append((stock, headlines, confidence, composite))

    if not positive_results:
        send_telegram(
            f"🔍 <b>S&P 500 Long-Term Scanner</b>\n\n"
            f"ผ่านเกณฑ์กราฟ {len(candidates)} ตัว\n"
            f"แต่ไม่มีข่าว Positive วันนี้ 📭"
        )
        return

    positive_results.sort(key=lambda x: x[3], reverse=True)
    top_results  = positive_results[:TOP_N]
    total_passed = len(positive_results)

    # ── บันทึกลง Google Sheets ─────────────────────────────────────────────
    save_to_sheet(top_results, scan_date)

    # ── Summary Leaderboard ────────────────────────────────────────────────
    rank_medals  = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    summary_rows = ""
    for rank, (stock, headlines, confidence, composite) in enumerate(top_results):
        medal    = rank_medals[rank] if rank < len(rank_medals) else f"{rank+1}."
        sent_pct = f"{confidence*100:.0f}%"
        summary_rows += (
            f"{medal} <b>${stock['ticker']}</b>  "
            f"Tech:{stock['score']}/10  Sentiment:{sent_pct}\n"
            f"    RSI {stock['rsi']} | ADX {stock['adx']} | "
            f"ห่าง 52W -{stock['pct_from_52w']:.1f}%\n"
        )

    send_telegram(
        f"🚨 <b>S&P 500 LONG-TERM SCAN — TOP {TOP_N}</b> 🚨\n"
        f"จากหุ้น Positive ทั้งหมด {total_passed} ตัว "
        f"(ผ่านเกณฑ์กราฟ {len(candidates)} ตัว)\n"
        f"<i>จัดอันดับจาก Technical Score + Sentiment Confidence</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{summary_rows}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 ≥9  🥇 ≥8  🥈 ≥7  🥉 ≥6  (Technical Score)"
    )
    time.sleep(2)

    for rank, (stock, headlines, confidence, composite) in enumerate(top_results):
        ok = send_telegram(build_message(stock, headlines, confidence, rank + 1))
        log.info(
            f"ส่ง #{rank+1} {stock['ticker']} "
            f"Tech:{stock['score']} Sent:{confidence*100:.0f}% Composite:{composite:.2f} "
            f"→ {'✅' if ok else '❌'}"
        )
        time.sleep(3)

    log.info(f"  เสร็จสิ้น! ส่ง Top {len(top_results)} จาก {total_passed} ตัว Positive")


# ══════════════════════════════════════════════
#  HTML Dashboard Template
# ══════════════════════════════════════════════
DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="th">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>S&P 500 Scanner — History</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:wght@400;700&family=Noto+Sans+Thai:wght@300;400;600&display=swap" rel="stylesheet">
<style>
  :root {
    --bg:        #0a0e17;
    --surface:   #111827;
    --border:    #1e2d40;
    --accent:    #00d4ff;
    --green:     #00e676;
    --gold:      #ffd700;
    --red:       #ff5252;
    --muted:     #4a5568;
    --text:      #e2e8f0;
    --subtext:   #8899aa;
    --font-mono: 'Space Mono', monospace;
    --font-th:   'Noto Sans Thai', sans-serif;
  }
  * { box-sizing: border-box; margin: 0; padding: 0; }

  body {
    background: var(--bg);
    color: var(--text);
    font-family: var(--font-th);
    min-height: 100vh;
    overflow-x: hidden;
  }

  /* Grid background */
  body::before {
    content: '';
    position: fixed; inset: 0; z-index: 0;
    background-image:
      linear-gradient(rgba(0,212,255,0.03) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,212,255,0.03) 1px, transparent 1px);
    background-size: 40px 40px;
    pointer-events: none;
  }

  .wrapper { position: relative; z-index: 1; max-width: 1400px; margin: 0 auto; padding: 32px 24px; }

  /* ── Header ── */
  header {
    display: flex; align-items: flex-end; justify-content: space-between;
    margin-bottom: 40px; flex-wrap: wrap; gap: 16px;
  }
  .logo-block { display: flex; flex-direction: column; gap: 4px; }
  .logo-title {
    font-family: var(--font-mono); font-size: 1.5rem; font-weight: 700;
    color: var(--accent); letter-spacing: 0.05em;
    text-shadow: 0 0 24px rgba(0,212,255,0.4);
  }
  .logo-sub { font-size: 0.78rem; color: var(--subtext); font-family: var(--font-mono); }

  .header-meta {
    display: flex; gap: 20px; align-items: center; flex-wrap: wrap;
  }
  .stat-pill {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 6px; padding: 8px 16px;
    display: flex; flex-direction: column; align-items: center; gap: 2px;
  }
  .stat-pill .num { font-family: var(--font-mono); font-size: 1.2rem; color: var(--accent); font-weight: 700; }
  .stat-pill .lbl { font-size: 0.68rem; color: var(--subtext); text-transform: uppercase; letter-spacing: 0.08em; }

  /* ── Filter bar ── */
  .filter-bar {
    display: flex; gap: 12px; margin-bottom: 24px; flex-wrap: wrap; align-items: center;
  }
  .filter-bar label { font-size: 0.78rem; color: var(--subtext); }
  .filter-bar input, .filter-bar select {
    background: var(--surface); border: 1px solid var(--border);
    color: var(--text); border-radius: 6px; padding: 7px 12px;
    font-family: var(--font-mono); font-size: 0.8rem; outline: none;
    transition: border-color 0.2s;
  }
  .filter-bar input:focus, .filter-bar select:focus { border-color: var(--accent); }
  .filter-bar input { width: 160px; }

  /* ── Table ── */
  .table-wrap {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; overflow: hidden;
  }
  table { width: 100%; border-collapse: collapse; }
  thead th {
    background: #0d1520; padding: 12px 14px;
    font-family: var(--font-mono); font-size: 0.68rem;
    color: var(--subtext); text-transform: uppercase;
    letter-spacing: 0.1em; text-align: left;
    border-bottom: 1px solid var(--border);
    white-space: nowrap; cursor: pointer; user-select: none;
  }
  thead th:hover { color: var(--accent); }
  thead th.sorted { color: var(--accent); }
  thead th.sorted::after { content: ' ▼'; font-size: 0.6em; }
  thead th.sorted.asc::after { content: ' ▲'; }

  tbody tr {
    border-bottom: 1px solid var(--border);
    transition: background 0.15s;
    animation: fadeIn 0.3s ease both;
  }
  tbody tr:last-child { border-bottom: none; }
  tbody tr:hover { background: rgba(0,212,255,0.04); }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; } }

  td {
    padding: 11px 14px; font-size: 0.82rem; vertical-align: middle;
    white-space: nowrap;
  }

  /* ── Ticker cell ── */
  .ticker-cell {
    font-family: var(--font-mono); font-weight: 700; font-size: 0.9rem;
    color: var(--accent);
  }
  .rank-badge {
    display: inline-block; width: 22px; height: 22px;
    border-radius: 50%; background: var(--border);
    font-size: 0.68rem; font-family: var(--font-mono);
    text-align: center; line-height: 22px; color: var(--subtext);
    margin-right: 6px;
  }
  .rank-1 { background: #ffd700; color: #000; }
  .rank-2 { background: #c0c0c0; color: #000; }
  .rank-3 { background: #cd7f32; color: #fff; }

  /* ── Score bar ── */
  .score-wrap { display: flex; align-items: center; gap: 8px; }
  .score-bar-outer {
    width: 80px; height: 6px; background: var(--border);
    border-radius: 3px; overflow: hidden;
  }
  .score-bar-inner {
    height: 100%; border-radius: 3px;
    background: linear-gradient(90deg, #00e676, #00d4ff);
    transition: width 0.6s ease;
  }
  .score-num { font-family: var(--font-mono); font-size: 0.78rem; color: var(--text); min-width: 28px; }

  /* ── Confidence badge ── */
  .conf-badge {
    font-family: var(--font-mono); font-size: 0.72rem;
    padding: 3px 8px; border-radius: 4px;
    background: rgba(0,230,118,0.12); color: var(--green);
    border: 1px solid rgba(0,230,118,0.25);
  }

  /* ── RSI color ── */
  .rsi-low  { color: var(--green); }
  .rsi-mid  { color: var(--gold); }
  .rsi-high { color: var(--red); }

  /* ── MACD ── */
  .macd-pos { color: var(--green); }
  .macd-neg { color: var(--red); }

  /* ── News tooltip ── */
  .news-cell { position: relative; max-width: 240px; }
  .news-preview {
    overflow: hidden; text-overflow: ellipsis;
    white-space: nowrap; color: var(--subtext);
    font-size: 0.75rem; cursor: pointer;
  }
  .news-preview:hover { color: var(--text); }
  .news-tooltip {
    display: none; position: absolute; left: 0; top: calc(100% + 4px); z-index: 100;
    background: #1a2535; border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 14px; width: 320px;
    font-size: 0.75rem; line-height: 1.6;
    box-shadow: 0 8px 32px rgba(0,0,0,0.5);
    white-space: normal;
  }
  .news-cell:hover .news-tooltip { display: block; }

  /* ── Date group separator ── */
  tr.date-sep td {
    background: rgba(0,212,255,0.06);
    font-family: var(--font-mono); font-size: 0.7rem;
    color: var(--accent); letter-spacing: 0.1em;
    padding: 6px 14px; border-bottom: 1px solid var(--border);
    border-top: 2px solid rgba(0,212,255,0.2);
  }

  /* ── Empty state ── */
  .empty {
    padding: 80px 24px; text-align: center; color: var(--muted);
  }
  .empty .icon { font-size: 3rem; margin-bottom: 12px; }
  .empty p { font-size: 0.9rem; }

  /* ── Config panel ── */
  .config-grid {
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(180px, 1fr));
    gap: 12px; margin-bottom: 32px;
  }
  .config-card {
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 8px; padding: 12px 14px;
  }
  .config-card .key {
    font-family: var(--font-mono); font-size: 0.65rem;
    color: var(--subtext); text-transform: uppercase;
    letter-spacing: 0.08em; margin-bottom: 4px;
  }
  .config-card .val {
    font-family: var(--font-mono); font-size: 0.88rem; color: var(--accent);
  }

  /* ── Loading overlay ── */
  #loading {
    position: fixed; inset: 0; background: rgba(10,14,23,0.85);
    display: flex; align-items: center; justify-content: center;
    z-index: 999; flex-direction: column; gap: 12px;
    font-family: var(--font-mono); color: var(--accent);
  }
  .spinner {
    width: 36px; height: 36px;
    border: 3px solid var(--border);
    border-top-color: var(--accent);
    border-radius: 50%;
    animation: spin 0.8s linear infinite;
  }
  @keyframes spin { to { transform: rotate(360deg); } }

  footer {
    margin-top: 48px; text-align: center;
    font-size: 0.72rem; color: var(--muted);
    font-family: var(--font-mono); line-height: 1.8;
  }

  @media (max-width: 768px) {
    .hide-mobile { display: none; }
    td, th { padding: 10px 8px; }
  }
</style>
</head>
<body>

<div id="loading">
  <div class="spinner"></div>
  <span>กำลังโหลดข้อมูล…</span>
</div>

<div class="wrapper">

  <!-- Header -->
  <header>
    <div class="logo-block">
      <div class="logo-title">◈ S&P 500 SCANNER</div>
      <div class="logo-sub">Long-Term • 4-Layer Filter • History Dashboard</div>
    </div>
    <div class="header-meta">
      <div class="stat-pill">
        <span class="num" id="stat-days">—</span>
        <span class="lbl">วันที่สแกน</span>
      </div>
      <div class="stat-pill">
        <span class="num" id="stat-records">—</span>
        <span class="lbl">ระเบียนทั้งหมด</span>
      </div>
      <div class="stat-pill">
        <span class="num" id="stat-tickers">—</span>
        <span class="lbl">Ticker ไม่ซ้ำ</span>
      </div>
    </div>
  </header>

  <!-- Filter config display -->
  <div class="config-grid" id="config-grid"></div>

  <!-- Filter bar -->
  <div class="filter-bar">
    <label>🔍</label>
    <input type="text" id="search" placeholder="ค้นหา Ticker…">
    <label>วันที่</label>
    <input type="date" id="filter-date">
    <label>เรียงโดย</label>
    <select id="sort-col">
      <option value="date">วันที่</option>
      <option value="composite">Composite Score</option>
      <option value="score">Tech Score</option>
      <option value="confidence">Sentiment</option>
      <option value="rsi">RSI</option>
    </select>
    <select id="sort-dir">
      <option value="desc">มากไปน้อย</option>
      <option value="asc">น้อยไปมาก</option>
    </select>
  </div>

  <!-- Table -->
  <div class="table-wrap">
    <table id="main-table">
      <thead>
        <tr>
          <th>วันที่</th>
          <th>#</th>
          <th>Ticker</th>
          <th>Tech Score</th>
          <th>Sentiment</th>
          <th>Composite</th>
          <th>ราคา</th>
          <th class="hide-mobile">RSI</th>
          <th class="hide-mobile">ADX</th>
          <th class="hide-mobile">MACD Hist</th>
          <th class="hide-mobile">ห่าง 52W High</th>
          <th class="hide-mobile">EMA50 Entry</th>
          <th class="hide-mobile">EMA200 Entry</th>
          <th>ราคาปัจจุบัน</th>
          <th>เปลี่ยนแปลง</th>
          <th>ข่าว</th>
        </tr>
      </thead>
      <tbody id="table-body">
      </tbody>
    </table>
  </div>

  <footer>
    <p>⚠️ ข้อมูลนี้เพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำการลงทุน</p>
    <p>S&P 500 Scanner Bot — Render + Hugging Face + Google Sheets</p>
  </footer>
</div>

<script>
const CONFIG = {{ config | tojson }};
const RAW    = {{ rows | tojson }};

// ── Config display ───────────────────────────
const configGrid = document.getElementById('config-grid');
const cfgItems = [
  ['Trend',   CONFIG.layer1_trend],
  ['EMA Slope', CONFIG.layer1_slope],
  ['ADX',     CONFIG.layer1_adx],
  ['RSI',     CONFIG.layer2_rsi],
  ['MACD',    CONFIG.layer2_macd],
  ['Volume',  CONFIG.layer3_volume],
  ['Min Score', CONFIG.min_score],
];
cfgItems.forEach(([k,v]) => {
  configGrid.innerHTML += `
    <div class="config-card">
      <div class="key">${k}</div>
      <div class="val">${v}</div>
    </div>`;
});

// ── Stats ────────────────────────────────────
const uniqueDates   = new Set(RAW.map(r => r.date)).size;
const uniqueTickers = new Set(RAW.map(r => r.ticker)).size;
document.getElementById('stat-days').textContent    = uniqueDates;
document.getElementById('stat-records').textContent = RAW.length;
document.getElementById('stat-tickers').textContent = uniqueTickers;

// ── Render table ─────────────────────────────
function rsiClass(v) {
  if (v <= 50) return 'rsi-low';
  if (v <= 60) return 'rsi-mid';
  return 'rsi-high';
}
function scoreColor(s) {
  if (s >= 9) return '#ffd700';
  if (s >= 8) return '#00e676';
  if (s >= 7) return '#00d4ff';
  return '#8899aa';
}

let currentData = [...RAW];

function renderTable(data) {
  const tbody = document.getElementById('table-body');
  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="16">
      <div class="empty">
        <div class="icon">📭</div>
        <p>ไม่พบข้อมูลที่ตรงกับเกณฑ์</p>
      </div>
    </td></tr>`;
    return;
  }

  let html = '';
  let lastDate = null;

  data.forEach((r, i) => {
    // Date separator
    if (r.date !== lastDate) {
      html += `<tr class="date-sep"><td colspan="16">📅  ${r.date}</td></tr>`;
      lastDate = r.date;
    }

    const rankBadge = r.rank <= 3
      ? `<span class="rank-badge rank-${r.rank}">${['🥇','🥈','🥉'][r.rank-1]}</span>`
      : `<span class="rank-badge">${r.rank}</span>`;

    const scoreW = (r.score / 10 * 100).toFixed(0);
    const confPct = (r.confidence * 100).toFixed(0);
    const macdClass = r.macd_hist >= 0 ? 'macd-pos' : 'macd-neg';
    const macdSign  = r.macd_hist >= 0 ? '+' : '';

    const headlines = (r.headlines || '').split(' | ');
    const newsPreview = headlines[0] || '—';
    const newsFull = headlines.map((h,i) => `${i+1}. ${h}`).join('<br>');

    // ── ราคาปัจจุบัน + % เปลี่ยนแปลง ──────────────────────────────────────
    const curPrice  = parseFloat(r.current_price);
    const changePct = parseFloat(r.change_pct);
    const curPriceStr = isNaN(curPrice)
      ? '<span style="color:var(--muted)">—</span>'
      : `$${curPrice.toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}`;
    let changePctStr = '<span style="color:var(--muted)">—</span>';
    if (!isNaN(changePct)) {
      const sign  = changePct >= 0 ? '+' : '';
      const color = changePct >= 0 ? 'var(--green)' : 'var(--red)';
      const arrow = changePct >= 0 ? '▲' : '▼';
      changePctStr = `<span style="font-family:var(--font-mono);color:${color};font-weight:700">${arrow} ${sign}${changePct.toFixed(2)}%</span>`;
    }

    html += `<tr style="animation-delay:${i*20}ms">
      <td style="font-family:var(--font-mono);font-size:0.75rem;color:var(--subtext)">${r.date}</td>
      <td>${rankBadge}</td>
      <td class="ticker-cell">$${r.ticker}</td>
      <td>
        <div class="score-wrap">
          <div class="score-bar-outer">
            <div class="score-bar-inner" style="width:${scoreW}%;background:linear-gradient(90deg,${scoreColor(r.score)},${scoreColor(r.score)}88)"></div>
          </div>
          <span class="score-num" style="color:${scoreColor(r.score)}">${r.score}/10</span>
        </div>
      </td>
      <td><span class="conf-badge">🟢 ${confPct}%</span></td>
      <td style="font-family:var(--font-mono);font-weight:700;color:var(--gold)">${parseFloat(r.composite||0).toFixed(2)}</td>
      <td style="font-family:var(--font-mono)">$${parseFloat(r.price||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
      <td class="hide-mobile ${rsiClass(r.rsi)}" style="font-family:var(--font-mono)">${r.rsi}</td>
      <td class="hide-mobile" style="font-family:var(--font-mono)">${r.adx}</td>
      <td class="hide-mobile ${macdClass}" style="font-family:var(--font-mono)">${macdSign}${parseFloat(r.macd_hist||0).toFixed(4)}</td>
      <td class="hide-mobile" style="font-family:var(--font-mono);color:var(--subtext)">-${r.pct_from_52w}%</td>
      <td class="hide-mobile" style="font-family:var(--font-mono);color:var(--green)">$${parseFloat(r.entry_ema50||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
      <td class="hide-mobile" style="font-family:var(--font-mono);color:var(--subtext)">$${parseFloat(r.entry_ema200||0).toLocaleString('en-US',{minimumFractionDigits:2,maximumFractionDigits:2})}</td>
      <td style="font-family:var(--font-mono)">${curPriceStr}</td>
      <td>${changePctStr}</td>
      <td class="news-cell">
        <div class="news-preview">${newsPreview}</div>
        <div class="news-tooltip">${newsFull}</div>
      </td>
    </tr>`;
  });

  tbody.innerHTML = html;
}

// ── Filter & Sort ────────────────────────────
function applyFilters() {
  const search  = document.getElementById('search').value.toLowerCase();
  const dateVal = document.getElementById('filter-date').value;
  const sortCol = document.getElementById('sort-col').value;
  const sortDir = document.getElementById('sort-dir').value;

  let data = [...RAW];

  if (search) data = data.filter(r => r.ticker.toLowerCase().includes(search));
  if (dateVal) data = data.filter(r => r.date === dateVal);

  const multiplier = sortDir === 'desc' ? -1 : 1;
  data.sort((a, b) => {
    let av = a[sortCol], bv = b[sortCol];
    let cmp;
    if (typeof av === 'string') cmp = av.localeCompare(bv) * multiplier;
    else cmp = (av - bv) * multiplier;
    // secondary sort: ถ้า primary เท่ากัน ให้เรียง rank 1→5 เสมอ
    if (cmp === 0) return (a.rank || 0) - (b.rank || 0);
    return cmp;
  });

  renderTable(data);
}

['search','filter-date','sort-col','sort-dir'].forEach(id => {
  document.getElementById(id).addEventListener('input', applyFilters);
});

// ── Initial render ───────────────────────────
renderTable(RAW);
document.getElementById('loading').style.display = 'none';
</script>
</body>
</html>"""


# ══════════════════════════════════════════════
#  Flask Routes
# ══════════════════════════════════════════════
@app.route("/")
def index():
    """
    หน้าหลัก — Web Dashboard ดึงประวัติจาก Google Sheets
    หากยังไม่ได้ตั้งค่า Google Sheets จะแสดง config เปล่าๆ
    """
    rows   = read_sheet_data(limit=300)
    config = {
        "layer1_trend":  "price > EMA20 > EMA50 > EMA200",
        "layer1_slope":  f"EMA50 slope >= {MIN_EMA50_SLOPE}%",
        "layer1_adx":    f">= {MIN_ADX}",
        "layer2_rsi":    f"{RSI_LOW}–{RSI_HIGH}",
        "layer2_macd":   f"histogram > {MIN_MACD_HIST}",
        "layer3_volume": f">= {MIN_AVG_VOLUME/1e6:.0f}M",
        "min_score":     f"{MIN_SCORE}/10",
    }
    return render_template_string(DASHBOARD_HTML, rows=rows, config=config)


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
        "message": "LONG-TERM SCANNER เริ่มสแกนแล้ว 🔍",
        "filters": f"Score>={MIN_SCORE} | ADX>{MIN_ADX} | RSI {RSI_LOW}–{RSI_HIGH}",
    })


@app.route("/health")
def health():
    sheet_ok = bool(GOOGLE_SHEET_ID and GOOGLE_SERVICE_ACCOUNT_JSON)
    return jsonify({
        "status":       "healthy",
        "google_sheets": "configured" if sheet_ok else "not configured",
    })


# ══════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)