import json
import gspread
from google.oauth2.service_account import Credentials
from config import *
from logger import log

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
    "roe", "debt_equity", "profit_margin", "div_yield",
    "pe_ratio", "forward_pe", "peg_ratio", "pb_ratio",
    "rev_growth", "earnings_growth", "valuation_flag",
    "sector",
    "stop_loss", "trail_stop", "take_profit", "rr_ratio",
    "atr",
    "entry_fib_236", "entry_fib_382", "entry_fib_500",
    "position_shares", "position_amount", "position_risk",
    "valuation_score",
    "sentiment_pos", "sentiment_neg", "sentiment_neu",
    # ── Features ใหม่ ──
    "timing_signal", "pct_above_ema20",
    "rs_vs_spy",
    "analyst_rec", "target_price", "upside_pct", "num_analysts", "analyst_score",
    "days_to_earnings", "earnings_warning",
    "fcf_positive", "rev_growing", "quality_score",
    "insider_action", "insider_score",
    "appearance_streak", "streak_bonus",
    "sector_flow", "sector_flow_score",
    "market_regime",
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
            # ขยาย columns ถ้า Sheet มีน้อยกว่าที่ต้องการ
            if ws.col_count < len(SHEET_HEADERS):
                ws.resize(rows=ws.row_count, cols=len(SHEET_HEADERS))
                log.info(f"ขยาย Sheet เป็น {len(SHEET_HEADERS)} columns")
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


def save_to_sheet(results: list, scan_date: str, market_regime: str = "bull"):
    """
    บันทึก Top N ลง Google Sheets
    results = list of (stock_dict, headlines_list, confidence_float, composite_float, sentiment_breakdown)
    """
    ws = get_gsheet()
    if ws is None:
        return

    rows = []
    for rank, item in enumerate(results, 1):
        # รองรับทั้ง tuple 5 ตัว (เก่า) และ 6 ตัว (ใหม่ มี sent_label)
        if len(item) == 6:
            stock, headlines, confidence, composite, sent_bk, sent_label = item
        elif len(item) == 5:
            stock, headlines, confidence, composite, sent_bk = item
            sent_label = 'positive'  # backward-compat
        else:
            stock, headlines, confidence, composite = item
            sent_bk = {"positive": 0, "negative": 0, "neutral": 0}
            sent_label = 'positive'

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
            sent_label,          # บันทึก sentiment label ที่แท้จริง (positive/neutral/negative)
            round(confidence, 4),
            round(composite, 4),
            stock.get("entry_current", ""),
            stock.get("entry_ema50", ""),
            stock.get("entry_ema200", ""),
            " | ".join(headlines),
            '=IFERROR(GOOGLEFINANCE(INDIRECT("B"&ROW()),"price"),"")',
            '=IFERROR((INDIRECT("W"&ROW())-INDIRECT("D"&ROW()))/INDIRECT("D"&ROW())*100,"")',
            stock.get("roe", ""),
            stock.get("debt_equity", ""),
            stock.get("profit_margin", ""),
            stock.get("div_yield", ""),
            stock.get("pe_ratio", ""),
            stock.get("forward_pe", ""),
            stock.get("peg_ratio", ""),
            stock.get("pb_ratio", ""),
            stock.get("rev_growth", ""),
            stock.get("earnings_growth", ""),
            stock.get("valuation_flag", ""),
            stock.get("sector", ""),
            stock.get("stop_loss", ""),
            stock.get("trail_stop", ""),
            stock.get("take_profit", ""),
            stock.get("rr_ratio", ""),
            stock.get("atr", ""),
            stock.get("entry_fib_236", ""),
            stock.get("entry_fib_382", ""),
            stock.get("entry_fib_500", ""),
            stock.get("position_shares", ""),
            stock.get("position_amount", ""),
            stock.get("position_risk", ""),
            stock.get("valuation_score", ""),
            sent_bk.get("positive", 0),
            sent_bk.get("negative", 0),
            sent_bk.get("neutral", 0),
            # ── Features ใหม่ ──
            stock.get("timing_signal", ""),
            stock.get("pct_above_ema20", ""),
            stock.get("rs_vs_spy", ""),
            stock.get("analyst_rec", ""),
            stock.get("target_price", ""),
            stock.get("upside_pct", ""),
            stock.get("num_analysts", ""),
            stock.get("analyst_score", ""),
            stock.get("days_to_earnings", ""),
            stock.get("earnings_warning", ""),
            stock.get("fcf_positive", ""),
            stock.get("rev_growing", ""),
            stock.get("quality_score", ""),
            stock.get("insider_action", ""),
            stock.get("insider_score", ""),
            stock.get("appearance_streak", ""),
            stock.get("streak_bonus", ""),
            stock.get("sector_flow", ""),
            stock.get("sector_flow_score", ""),
            market_regime,
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
#  Historical Consistency — นับวันที่หุ้นปรากฏในผลสแกน
# ══════════════════════════════════════════════

def get_ticker_streak(ticker: str, lookback_days: int = 30) -> int:
    """
    นับจำนวนวัน (ไม่ซ้ำ) ที่หุ้นตัวนี้ปรากฏในผลสแกนภายใน lookback_days วันที่ผ่านมา
    Return: จำนวนวัน (0 ถ้าไม่เคยปรากฏ หรือไม่มี Google Sheets)
    """
    from datetime import datetime, timezone, timedelta
    ws = get_gsheet()
    if ws is None:
        return 0
    try:
        all_rows = ws.get_all_records()
        cutoff   = (datetime.now(timezone.utc) - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
        dates_appeared = set()
        for row in all_rows:
            row_date   = str(row.get("date", ""))
            row_ticker = str(row.get("ticker", ""))
            if row_ticker == ticker and row_date >= cutoff:
                dates_appeared.add(row_date)
        count = len(dates_appeared)
        if count > 0:
            log.debug(f"[Streak] {ticker}: ปรากฏ {count} วัน ใน {lookback_days} วันที่ผ่านมา")
        return count
    except Exception as e:
        log.debug(f"[Streak] ดึงข้อมูล {ticker} ล้มเหลว: {e}")
        return 0


# ══════════════════════════════════════════════
#  Backtesting Support — ดึงประวัติรายละเอียดย้อนหลัง
# ══════════════════════════════════════════════

def get_scan_history(days: int = 90) -> list:
    """
    ดึงประวัติ Signal ย้อนหลังจาก Google Sheets สำหรับ Backtesting Engine

    Parameters
    ----------
    days : int
        จำนวนวันย้อนหลัง (default 90)

    Returns
    -------
    list of dict พร้อม fields: ticker, date, price, stop_loss, take_profit,
                                     composite, sentiment, rank
    """
    ws = get_gsheet()
    if ws is None:
        log.warning("[ScanHistory] Google Sheets ไม่ได้ตั้งค่า")
        return []
    try:
        from datetime import datetime, timezone, timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%d")
        all_rows = ws.get_all_records()
        history  = []
        for row in all_rows:
            row_date = str(row.get("date", ""))
            if row_date >= cutoff:
                history.append({
                    'ticker':     str(row.get('ticker', '')),
                    'date':       row_date,
                    'price':      row.get('price') or row.get('entry_current'),
                    'stop_loss':  row.get('stop_loss'),
                    'take_profit':row.get('take_profit'),
                    'composite':  row.get('composite'),
                    'sentiment':  row.get('sentiment', 'positive'),
                    'rank':       row.get('rank'),
                })
        log.info(f"[ScanHistory] ดึง {len(history)} Signal (ย้อนหลัง {days} วัน)")
        return history
    except Exception as e:
        log.error(f"[ScanHistory] ดึงข้อมูลล้มเหลว: {e}")
        return []
