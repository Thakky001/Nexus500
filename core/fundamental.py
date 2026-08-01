import yfinance as yf
from config import *
from logger import log

# ══════════════════════════════════════════════
def check_fundamentals(ticker: str) -> tuple:
    """ดึงข้อมูลงบการเงิน + Valuation และคัดกรองความแข็งแกร่ง"""
    try:
        info = yf.Ticker(ticker).info
        
        roe = info.get('returnOnEquity', 0) or 0
        de = info.get('debtToEquity', 999) or 999
        margin = info.get('profitMargins', 0) or 0
        div = info.get('dividendYield', 0) or 0
        sector = info.get('sector', 'Unknown')

        pe_ratio       = info.get('trailingPE', 0) or 0
        forward_pe     = info.get('forwardPE', 0) or 0
        peg_ratio      = info.get('pegRatio', 0) or 0
        pb_ratio       = info.get('priceToBook', 0) or 0
        rev_growth     = info.get('revenueGrowth', 0) or 0
        earnings_growth = info.get('earningsGrowth', 0) or 0

        passed = True
        valuation_flag = "fair"

        if sector != 'Financial Services':
            if de > MAX_DEBT_EQUITY: passed = False
            
        if roe < MIN_ROE: passed = False
        if margin < MIN_PROFIT_MARGIN: passed = False

        if pe_ratio > 0:
            if pe_ratio > MAX_PE_RATIO:
                valuation_flag = "expensive"
            elif pe_ratio < 15:
                valuation_flag = "cheap"
        
        if peg_ratio > MAX_PEG_RATIO and peg_ratio > 0:
            valuation_flag = "expensive"

        # Valuation Score
        val_score = 0
        if 0 < pe_ratio <= 25: val_score += 1
        if 0 < peg_ratio <= 1.5: val_score += 1
        if rev_growth > 0.10: val_score += 1

        details = {
            "roe": round(roe * 100, 2),
            "debt_equity": round(de / 100, 2), # แปลง % เป็นเท่า
            "profit_margin": round(margin * 100, 2),
            "div_yield": round(div * 100, 2),
            "pe_ratio": round(pe_ratio, 2),
            "forward_pe": round(forward_pe, 2),
            "peg_ratio": round(peg_ratio, 2),
            "pb_ratio": round(pb_ratio, 2),
            "rev_growth": round(rev_growth * 100, 2),
            "earnings_growth": round(earnings_growth * 100, 2),
            "valuation_flag": valuation_flag,
            "valuation_score": val_score,
            "sector": sector,
        }
        return passed, details
    except Exception as e:
        log.debug(f"ดึงข้อมูลงบ {ticker} ล้มเหลว: {e}")
        return False, {
            "roe": 0, "debt_equity": 0, "profit_margin": 0, "div_yield": 0,
            "pe_ratio": 0, "forward_pe": 0, "peg_ratio": 0, "pb_ratio": 0,
            "rev_growth": 0, "earnings_growth": 0, "valuation_flag": "unknown",
            "valuation_score": 0, "sector": "Unknown"
        }


# ══════════════════════════════════════════════

