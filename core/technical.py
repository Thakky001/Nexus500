import time
import io
import requests
import pandas as pd
import pandas_ta_classic as ta
import yfinance as yf
from config import *
from logger import log

# ── SPY data สำหรับ Relative Strength (โหลดครั้งเดียวต่อ 1 scan run) ─────
_spy_df_cache = None


def _get_spy_df() -> pd.DataFrame:
    """โหลด SPY data แบบ lazy cache — ดึงครั้งเดียวตลอดการสแกน"""
    global _spy_df_cache
    if _spy_df_cache is not None and len(_spy_df_cache) > 0:
        return _spy_df_cache
    try:
        df = yf.download("SPY", period="1y", interval="1d",
                         auto_adjust=True, progress=False, threads=False)
        if df is not None and len(df) >= RS_PERIOD:
            _spy_df_cache = df
            log.info(f"[RS] โหลด SPY สำเร็จ: {len(df)} วัน")
        else:
            _spy_df_cache = pd.DataFrame()
    except Exception as e:
        log.warning(f"[RS] โหลด SPY ล้มเหลว: {e}")
        _spy_df_cache = pd.DataFrame()
    return _spy_df_cache


def reset_spy_cache():
    """เรียกตอนเริ่ม run_scan() ใหม่แต่ละรอบ เพื่อล้าง cache"""
    global _spy_df_cache
    _spy_df_cache = None

def get_sp500_tickers() -> list:
    """ฟังก์ชันสำรอง กรณีโหลด 1000 ตัวล้มเหลว"""
    url = "https://en.wikipedia.org/wiki/List_of_S%26P_500_companies"
    headers = {"User-Agent": "Mozilla/5.0"}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables  = pd.read_html(io.StringIO(resp.text), attrs={"id": "constituents"}, flavor='html5lib')
        tickers = tables[0]["Symbol"].str.replace(".", "-", regex=False).tolist()
        log.info(f"[Fallback] โหลด S&P 500 สำเร็จ: {len(tickers)} ตัว")
        return tickers
    except Exception as e:
        log.error(f"โหลด S&P 500 ล้มเหลว: {e}")
        return []

def get_all_us_tickers() -> list:
    """ดึงรายชื่อหุ้นทั้งหมดในตลาดอเมริกา (คัดเฉพาะหุ้นสามัญ)"""
    url = "https://raw.githubusercontent.com/rreichel3/US-Stock-Symbols/main/nasdaq/nasdaq_full_tickers.json"
    try:
        # ดึงจาก Github Raw ที่มีคนรวบรวมไว้แทน FTP เพื่อหลีกเลี่ยงการโดนบล็อค
        # แต่เพื่อความเสถียร ใช้ SEC API ดีกว่า
        sec_url = "https://www.sec.gov/files/company_tickers.json"
        headers = {"User-Agent": "Nexus500-StudentProject contact@example.com"}
        resp = requests.get(sec_url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        tickers = [info["ticker"] for info in data.values()]
        # กรองตัวอักษรแปลกๆ ออก (เก็บเฉพาะตัวอักษรภาษาอังกฤษ)
        tickers = [t for t in tickers if t.isalpha()]
        
        # คัดเอาเฉพาะ Top 5000 ตามมูลค่าตลาด (SEC JSON เรียงลำดับจากใหญ่ไปเล็กให้แล้ว)
        tickers = tickers[:5000]
        
        log.info(f"โหลดรายชื่อหุ้น US สำเร็จ: {len(tickers)} ตัว (จำกัดที่ Top 5000)")
        return tickers
    except Exception as e:
        log.error(f"โหลดรายชื่อหุ้น US ล้มเหลว: {e}")
        return get_1000_tickers()

def get_1000_tickers() -> list:
    """โหลดรายชื่อจาก Russell 1000 Index"""
    url = "https://en.wikipedia.org/wiki/Russell_1000_Index"
    headers = {"User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )}
    try:
        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        tables = pd.read_html(io.StringIO(resp.text), flavor='html5lib')
        for table in tables:
            if "Symbol" in table.columns:
                tickers = table["Symbol"].str.replace(".", "-", regex=False).tolist()
                log.info(f"โหลดรายชื่อ Russell 1000 สำเร็จ: {len(tickers)} ตัว")
                return tickers
            elif "Ticker" in table.columns:
                tickers = table["Ticker"].str.replace(".", "-", regex=False).tolist()
                log.info(f"โหลดรายชื่อ Russell 1000 สำเร็จ: {len(tickers)} ตัว")
                return tickers
        
        log.warning("ไม่พบคอลัมน์ Symbol ในตาราง Wikipedia — สลับไปใช้ S&P 500")
        return get_sp500_tickers()
    except Exception as e:
        log.error(f"โหลดรายชื่อ Russell 1000 ล้มเหลว: {e}")
        return get_sp500_tickers()


# ══════════════════════════════════════════════
#  STEP 2 — คัดกรอง 4 ชั้น + Scoring (Technical)
# ══════════════════════════════════════════════
def score_stock(df: pd.DataFrame, rsi_low: int = RSI_LOW, rsi_high: int = RSI_HIGH) -> tuple:
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

    # Fibonacci Entry Zones
    swing_low_60d = float(low.tail(60).min())
    fib_range     = price - swing_low_60d

    entry_zone_1 = round(price - fib_range * FIB_LEVELS[0], 2)
    entry_zone_2 = round(price - fib_range * FIB_LEVELS[1], 2)
    entry_zone_3 = round(price - fib_range * FIB_LEVELS[2], 2)
    entry_zone_3 = max(entry_zone_3, round(e200 * 1.02, 2))
    
    # ATR & Exit Levels
    atr    = ta.atr(high, low, close, length=14)
    atr_val = float(atr.iloc[-1]) if (atr is not None and not atr.empty) else 0.0
    
    stop_loss = round(e200 * (1 - STOP_LOSS_PCT / 100), 2)
    recent_high = float(high.tail(20).max())
    trail_stop  = round(recent_high - TRAIL_STOP_ATR_MULT * atr_val, 2)
    take_profit = round(price * (1 + TAKE_PROFIT_PCT / 100), 2)
    
    risk   = price - max(stop_loss, trail_stop)
    reward = take_profit - price
    rr_ratio = round(reward / risk, 2) if risk > 0 else 0

    # Position Sizing
    risk_per_share = abs(price - stop_loss)
    if risk_per_share <= 0:
        position_shares = 0
        invest_amount = 0
        risk_amount = 0
        pct_portfolio = 0
    else:
        max_risk_amount = PORTFOLIO_VALUE * (MAX_RISK_PER_TRADE / 100)
        shares_by_risk  = int(max_risk_amount / risk_per_share)
        max_invest = PORTFOLIO_VALUE * (MAX_POSITION_PCT / 100)
        shares_by_cap = int(max_invest / price)
        position_shares = min(shares_by_risk, shares_by_cap)
        invest_amount = round(position_shares * price, 2)
        risk_amount   = round(position_shares * risk_per_share, 2)
        pct_portfolio = round(invest_amount / PORTFOLIO_VALUE * 100, 1)

    details.update({
        "price": round(price, 2),       "ema20": round(e20, 2),
        "ema50": round(e50, 2),          "ema200": round(e200, 2),
        "rsi": round(rsi_val, 1),        "macd_hist": round(macd_hist, 4),
        "macd_line": round(macd_line, 4),"macd_sig": round(macd_sig, 4),
        "adx": round(adx_val, 1),        "e50_slope_pct": round(e50_slope_pct, 2),
        "pct_from_52w": round(pct_from_52w, 1), "momentum_5d": round(momentum_5d, 2),
        "avg_vol": int(avg_vol_20),      "vol_surge": round(vol_surge, 2),
        "entry_current": round(price, 2),
        "entry_ema50": round(e50, 2),
        "entry_ema200": round(e200, 2),
        "entry_fib_236": entry_zone_1,
        "entry_fib_382": entry_zone_2,
        "entry_fib_500": entry_zone_3,
        "stop_loss": stop_loss,
        "trail_stop": trail_stop,
        "take_profit": take_profit,
        "rr_ratio": rr_ratio,
        "atr": round(atr_val, 2),
        "position_shares": position_shares,
        "position_amount": invest_amount,
        "position_risk": risk_amount,
        "pct_portfolio": pct_portfolio,
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
    if not (rsi_low <= rsi_val <= rsi_high):
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

    # ── Timing Signal ──────────────────────────────────────────────────────
    pct_above_ema20 = ((price - e20) / e20 * 100) if e20 > 0 else 0.0

    if rsi_val <= TIMING_BUY_RSI_MAX and pct_above_ema20 <= TIMING_BUY_PCT_EMA20_MAX:
        timing = "🟢 BUY NOW"     # ราคาใกล้ EMA20 Support + RSI ไม่สูง
    elif rsi_val >= TIMING_EXT_RSI_MIN or pct_above_ema20 >= TIMING_EXT_PCT_EMA20_MIN:
        timing = "🔴 EXTENDED"    # RSI สูงเกินหรือราคาห่าง EMA20 มาก
    else:
        timing = "🟡 WAIT"        # หุ้นดีแต่ยังไม่ย่อพอ

    details["timing_signal"]   = timing
    details["pct_above_ema20"] = round(pct_above_ema20, 2)

    # ── Relative Strength vs SPY ───────────────────────────────────────────
    rs_vs_spy  = 0.0
    rs_bonus   = 0
    spy_df     = _get_spy_df()
    if not spy_df.empty and len(spy_df) >= RS_PERIOD and len(close) >= RS_PERIOD:
        try:
            stock_ret = (float(close.iloc[-1]) / float(close.iloc[-RS_PERIOD]) - 1) * 100
            spy_ret   = (float(spy_df["Close"].iloc[-1]) / float(spy_df["Close"].iloc[-RS_PERIOD]) - 1) * 100
            rs_vs_spy = round(stock_ret - spy_ret, 2)
            rs_bonus  = 1 if rs_vs_spy > 0 else 0
        except Exception:
            pass

    details["rs_vs_spy"] = rs_vs_spy
    details["rs_bonus"]  = rs_bonus
    
    score += rs_bonus

    return score, details


def fetch_and_filter(tickers: list, min_score: int = MIN_SCORE, rsi_low: int = RSI_LOW, rsi_high: int = RSI_HIGH) -> list:
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

                score, details = score_stock(df, rsi_low=rsi_low, rsi_high=rsi_high)

                if score >= min_score:
                    passed.append({"ticker": ticker, "score": score, **details})
                    log.info(
                        f"  ✅ {ticker} Score:{score}/10 | "
                        f"RSI:{details['rsi']} ADX:{details['adx']} "
                        f"MACDh:{details['macd_hist']} 5dM:{details['momentum_5d']}% "
                        f"RS:{details.get('rs_vs_spy', 0):+.1f}% {details.get('timing_signal','')}"
                    )
                elif score == -1:
                    log.debug(f"  ❌ {ticker} — {details.get('fail','?')}")
                else:
                    log.debug(f"  ⚠️ {ticker} Score:{score} (ต่ำกว่า {min_score})")

            except Exception as e:
                log.debug(f"  ❌ {ticker}: {e}")

        if idx < len(chunks):
            log.info(f"พัก {CHUNK_PAUSE}s...")
            time.sleep(CHUNK_PAUSE)

    passed.sort(key=lambda x: x["score"], reverse=True)
    log.info(f"ผ่านเกณฑ์ทั้งหมด: {len(passed)} ตัว (Score >= {min_score})")
    return passed


# ══════════════════════════════════════════════
#  STEP 2.5 — ตรวจสอบงบการเงิน (Fundamentals)

