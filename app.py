"""
╔══════════════════════════════════════════════════════════╗
║   S&P 500 Stock Scanner Bot  •  app.py  [LONG-TERM]      ║
║  Flask + yfinance + pandas-ta + FinBERT + Telegram       ║
╠══════════════════════════════════════════════════════════╣
║  ระบบคัดกรอง 4 ชั้น สำหรับการลงทุนระยะยาว / DCA สะสมหุ้น      ║
║  เน้นหุ้นพื้นฐานดีที่ยืนบนแนวโน้มขาขึ้น และรอรับเมื่อราคาย่อตัว      ║
╚══════════════════════════════════════════════════════════╝

Environment Variables บน Render:
  TELEGRAM_BOT_TOKEN   = token จาก @BotFather
  TELEGRAM_CHAT_ID     = Chat ID ของ Channel (ขึ้นต้นด้วย -100...)
  HF_API_TOKEN         = Hugging Face API Token
"""

import io
import os
import time
import threading
import logging

import requests
import pandas as pd
import pandas_ta_classic as ta
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

HF_MODEL_URL = "https://router.huggingface.co/hf-inference/models/ProsusAI/finbert"

# ══════════════════════════════════════════════
#  ⚙️  เกณฑ์คัดกรอง (ปรับสำหรับลงทุนระยะยาว)
# ══════════════════════════════════════════════

# ── ชั้น 1: Trend Alignment (บังคับ) ──
MIN_ADX           = 20      # เทรนด์ระยะยาว ไม่จำเป็นต้องพุ่งแรงตลอดเวลา
EMA_SLOPE_DAYS    = 20      # ดูภาพกว้างขึ้น (20 วัน)
MIN_EMA50_SLOPE   = 0.0     # แค่ความชันไม่ติดลบก็พอ (เป็นขาขึ้นหรือทรงตัว)

# ── ชั้น 2: Momentum (บังคับ) ─────────
RSI_LOW           = 40      # อนุญาตให้ RSI ย่อลงมาต่ำได้ เพื่อหาจังหวะเก็บของ
RSI_HIGH          = 70      # กันหุ้นที่แพงเกินไป (Overbought)
MIN_MACD_HIST     = -0.5    # ระยะยาว MACD Hist ติดลบได้นิดหน่อยเวลาราคาย่อ

# ── ชั้น 3: Volume Quality (บังคับ) ─────────
MIN_AVG_VOLUME    = 2_000_000  # ผ่อนปรนลงมาให้ครอบคลุมหุ้นพื้นฐานดีที่อาจไม่หวือหวา
MIN_VOL_SURGE     = 0.0        # ระยะยาวไม่ต้องสนใจ Volume เข้าออกรายวัน

# ── ชั้น 4: Price Structure (เพิ่มคะแนน) ────
MAX_PCT_FROM_52W  = 20.0    # ย่อได้ลึกถึง 20% จากจุดสูงสุด (มองเป็นส่วนลด)
MIN_5D_MOMENTUM   = -5.0    # ยอมรับการย่อตัวระยะสั้นได้

# ── Scoring: ส่ง Telegram เฉพาะ Score >= N ──
MIN_SCORE         = 6       # เกณฑ์ผ่าน (max = 10)

# ── Top N: คัดสุดท้ายเหลือกี่ตัว ─────────────
TOP_N             = 5       # แสดงเฉพาะ Top 5 (จัดอันดับจาก Composite Score)

# ── Rate Limit Protection ────────────────────
CHUNK_SIZE        = 50
CHUNK_PAUSE       = 10
NEWS_PAUSE        = 5
AI_PAUSE          = 20
AI_RETRY_WAIT     = 60

# ─────────────────────────────────────────────
app = Flask(__name__)


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
    """
    คัดกรองและให้คะแนนหุ้น 0–10
    คืนค่า (score, detail_dict)
    หาก fail ชั้นบังคับ จะคืน score = -1 พร้อมเหตุผล
    """
    score   = 0
    details = {}

    close  = df["Close"]
    high   = df["High"]
    low    = df["Low"]
    volume = df["Volume"]
    last   = df.iloc[-1]

    # ─── คำนวณ Indicators ทั้งหมด ───────────
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

    # MACD
    try:
        hist_col = [c for c in macd_df.columns if c.startswith("MACDh")][0]
        line_col = [c for c in macd_df.columns if c.startswith("MACD_")][0]
        sig_col  = [c for c in macd_df.columns if c.startswith("MACDs")][0]
        macd_hist = float(macd_df[hist_col].iloc[-1])
        macd_line = float(macd_df[line_col].iloc[-1])
        macd_sig  = float(macd_df[sig_col].iloc[-1])
    except Exception:
        macd_hist = macd_line = macd_sig = 0.0

    # ADX
    try:
        adx_col = [c for c in adx_df.columns if c.startswith("ADX")][0]
        adx_val = float(adx_df[adx_col].iloc[-1])
    except Exception:
        adx_val = 0.0

    # EMA50 Slope %
    e50_past      = float(ema50.iloc[-1 - EMA_SLOPE_DAYS])
    e50_slope_pct = ((e50 - e50_past) / e50_past * 100) if e50_past > 0 else 0.0

    # อื่นๆ
    pct_from_52w = ((high_52w - price) / high_52w * 100) if high_52w > 0 else 999.0
    momentum_5d  = ((price - price_5d) / price_5d * 100) if price_5d > 0 else 0.0
    vol_surge    = today_vol / avg_vol_20 if avg_vol_20 > 0 else 0.0

    # ─── Entry Levels (สำหรับระยะยาว) ────────────────
    # แบ่งไม้เข้า (DCA / Accumulation) ตามเส้นค่าเฉลี่ย
    entry_current  = price          # ไม้แรก: ราคาตลาดปัจจุบัน
    entry_ema50    = round(e50, 2)  # ไม้สอง: รอรับเมื่อย่อลงมาแตะ EMA50
    entry_ema200   = round(e200, 2) # ไม้สาม (ไม้ตาย): รอรับเมื่อเกิด Panic Sell ลงมาแตะ EMA200

    details.update({
        "price": round(price, 2), "ema20": round(e20, 2),
        "ema50": round(e50, 2),   "ema200": round(e200, 2),
        "rsi": round(rsi_val, 1), "macd_hist": round(macd_hist, 4),
        "macd_line": round(macd_line, 4), "macd_sig": round(macd_sig, 4),
        "adx": round(adx_val, 1), "e50_slope_pct": round(e50_slope_pct, 2),
        "pct_from_52w": round(pct_from_52w, 1), "momentum_5d": round(momentum_5d, 2),
        "avg_vol": int(avg_vol_20), "vol_surge": round(vol_surge, 2),
        # Trade levels (Long-term)
        "entry_current":  entry_current,
        "entry_ema50":    entry_ema50,
        "entry_ema200":   entry_ema200,
    })

    # ══════════════════════════════════════════
    #  ชั้น 1 — Trend Alignment (บังคับ) = 2 คะแนน
    # ══════════════════════════════════════════
    # 1a: Full EMA Stack — ราคา > EMA20 > EMA50 > EMA200
    if not (price > e20 > e50 > e200):
        details["fail"] = "EMA Stack ไม่ครบ"
        return -1, details

    # 1b: EMA50 Slope ต้องเป็นขาขึ้นหรือทรงตัว
    if e50_slope_pct < MIN_EMA50_SLOPE:
        details["fail"] = f"EMA50 Slope ต่ำ ({e50_slope_pct:.2f}%)"
        return -1, details

    # 1c: ADX > 20 — มีเทรนด์ระยะยาว
    if adx_val < MIN_ADX:
        details["fail"] = f"ADX ต่ำ ({adx_val:.1f} < {MIN_ADX})"
        return -1, details

    score += 2
    if adx_val >= 30:          # Bonus: เทรนด์แรง
        score += 1
        details["bonus_adx"] = True

    # ══════════════════════════════════════════
    #  ชั้น 2 — Momentum (บังคับ) = 2 คะแนน
    # ══════════════════════════════════════════
    if not (RSI_LOW <= rsi_val <= RSI_HIGH):
        details["fail"] = f"RSI ออกนอก Zone ({rsi_val:.1f})"
        return -1, details

    if macd_hist <= MIN_MACD_HIST:
        details["fail"] = f"MACD Hist ต่ำเกินไป ({macd_hist:.4f})"
        return -1, details

    score += 2
    if 40 <= rsi_val <= 55:    # Bonus: RSI โซนเก็บของ (ย่อตัวลงมา)
        score += 1
        details["bonus_rsi"] = True

    # ══════════════════════════════════════════
    #  ชั้น 3 — Volume Quality (บังคับ) = 2 คะแนน
    # ══════════════════════════════════════════
    if avg_vol_20 < MIN_AVG_VOLUME:
        details["fail"] = f"Volume ต่ำ ({avg_vol_20/1e6:.1f}M < {MIN_AVG_VOLUME/1e6:.0f}M)"
        return -1, details

    score += 2
    if vol_surge >= 1.5:       # Bonus: มีแรงซื้อผิดปกติ
        score += 1
        details["bonus_vol_surge"] = True

    # ══════════════════════════════════════════
    #  ชั้น 4 — Price Structure (เพิ่มคะแนน)
    # ══════════════════════════════════════════
    if pct_from_52w <= MAX_PCT_FROM_52W:   # ราคาไม่หลุดไกลจาก 52W High
        score += 1
        details["pass_52w"] = True

    if momentum_5d >= MIN_5D_MOMENTUM:     # โครงสร้างระยะสั้นไม่พัง
        score += 1
        details["pass_5d_mom"] = True

    return score, details


def fetch_and_filter(tickers: list) -> list:
    """ดาวน์โหลดกราฟ + รัน 4-layer filter + sorting ตาม Score"""
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
    """คืนค่า (label, confidence_score)"""
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

    rank_medals = {1: "🥇", 2: "🥈", 3: "🥉", 4: "4️⃣", 5: "5️⃣"}
    rank_label  = f"  #{rank} TODAY'S TOP" if rank else ""

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

    # ดึงค่า Entry
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
        f"🎯 <b>แผนการสะสม (Accumulation Zones)</b>\n"
        f"\n"
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

    # ── รวบรวม Positive results พร้อม Composite Score ──────────────────────
    # Composite Score = Technical Score (0-10) + Sentiment Confidence (0-1)
    # ทำให้ข่าวดีมาก (confidence 0.95) มีน้ำหนักเหนือกว่าข่าวดีพอใช้ (0.60)
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
            # Composite = technical score + sentiment bonus (max ~11)
            composite = stock["score"] + confidence
            positive_results.append((stock, headlines, confidence, composite))

    if not positive_results:
        send_telegram(
            f"🔍 <b>S&P 500 Long-Term Scanner</b>\n\n"
            f"ผ่านเกณฑ์กราฟ {len(candidates)} ตัว\n"
            f"แต่ไม่มีข่าว Positive วันนี้ 📭"
        )
        return

    # ── จัดอันดับด้วย Composite Score แล้วตัดเหลือ Top N ───────────────────
    positive_results.sort(key=lambda x: x[3], reverse=True)
    top_results  = positive_results[:TOP_N]
    total_passed = len(positive_results)

    # ── Summary Leaderboard Message ────────────────────────────────────────
    rank_medals = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
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

    # ── ส่งรายละเอียดแต่ละตัว ──────────────────────────────────────────────
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
#  Flask Routes
# ══════════════════════════════════════════════
@app.route("/")
def index():
    return jsonify({
        "status": "ok", "version": "v2-longterm",
        "filters": {
            "layer1_trend":   "price > EMA20 > EMA50 > EMA200",
            "layer1_slope":   f"EMA50 slope >= {MIN_EMA50_SLOPE}%",
            "layer1_adx":     f">= {MIN_ADX}",
            "layer2_rsi":     f"{RSI_LOW}–{RSI_HIGH}",
            "layer2_macd":    f"histogram > {MIN_MACD_HIST}",
            "layer3_volume":  f">= {MIN_AVG_VOLUME/1e6:.0f}M",
            "min_score":      f"{MIN_SCORE}/10",
        }
    })


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
        "status": "accepted",
        "message": "LONG-TERM SCANNER เริ่มสแกนแล้ว 🔍",
        "filters": f"Score>={MIN_SCORE} | ADX>{MIN_ADX} | RSI {RSI_LOW}–{RSI_HIGH}",
    })


@app.route("/health")
def health():
    return jsonify({"status": "healthy"})


# ══════════════════════════════════════════════
#  Entry Point
# ══════════════════════════════════════════════
if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port)