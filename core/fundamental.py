import yfinance as yf
import pandas as pd
from datetime import datetime, timezone
from config import *
from logger import log

# ==============================================================================
def check_fundamentals(ticker: str) -> tuple:
    """ดึงข้อมูลงบการเงิน + Valuation + Analyst + Earnings Calendar + Quality"""
    try:
        t    = yf.Ticker(ticker)
        info = t.info

        roe    = info.get('returnOnEquity', 0) or 0
        de     = info.get('debtToEquity', 999) or 999
        margin = info.get('profitMargins', 0) or 0
        div    = info.get('dividendYield', 0) or 0
        sector = info.get('sector', 'Unknown')

        pe_ratio        = info.get('trailingPE', 0) or 0
        forward_pe      = info.get('forwardPE', 0) or 0
        peg_ratio       = info.get('pegRatio', 0) or 0
        pb_ratio        = info.get('priceToBook', 0) or 0
        rev_growth      = info.get('revenueGrowth', 0) or 0
        earnings_growth = info.get('earningsGrowth', 0) or 0

        passed         = True
        valuation_flag = 'fair'

        if sector != 'Financial Services':
            if de > MAX_DEBT_EQUITY: passed = False

        if roe < MIN_ROE:              passed = False
        if margin < MIN_PROFIT_MARGIN: passed = False

        if pe_ratio > 0:
            if pe_ratio > MAX_PE_RATIO:
                valuation_flag = 'expensive'
            elif pe_ratio < 15:
                valuation_flag = 'cheap'

        if peg_ratio > MAX_PEG_RATIO and peg_ratio > 0:
            valuation_flag = 'expensive'

        # -- Valuation Score (0-3) -----------------------------------------------
        val_score = 0
        if 0 < pe_ratio <= 25:   val_score += 1
        if 0 < peg_ratio <= 1.5: val_score += 1
        if rev_growth > 0.10:    val_score += 1

        # -- Analyst Consensus ---------------------------------------------------
        recommendation = info.get('recommendationKey', 'none') or 'none'
        target_price   = info.get('targetMeanPrice', 0) or 0
        num_analysts   = info.get('numberOfAnalystOpinions', 0) or 0
        current_price  = info.get('currentPrice', 0) or 0

        upside_pct = 0.0
        if target_price > 0 and current_price > 0:
            upside_pct = ((target_price - current_price) / current_price) * 100

        # Analyst Score (0-3)
        analyst_score = 0
        if recommendation.lower() in ('strongbuy', 'strong_buy', 'buy'):
            analyst_score += 1
        if upside_pct >= MIN_ANALYST_UPSIDE:
            analyst_score += 1
        if num_analysts >= MIN_ANALYST_COUNT:
            analyst_score += 1

        # -- Earnings Calendar ---------------------------------------------------
        earnings_warning = ''
        days_to_earnings = None
        try:
            ed = t.get_earnings_dates(limit=4)
            if ed is not None and not ed.empty:
                now    = datetime.now(timezone.utc)
                future = ed.index[ed.index > now]
                if len(future) > 0:
                    next_earnings    = future[0]
                    days_to_earnings = int((next_earnings - now).days)
                    if days_to_earnings <= 7:
                        earnings_warning = f'⚠️ ประกาศงบอีก {days_to_earnings} วัน! ระวังความผันผวน'
                        passed = False
                        log.info(f"[Earnings] {ticker}: ปัดตก — ประกาศงบอีก {days_to_earnings} วัน")
                    elif days_to_earnings <= 14:
                        earnings_warning = f'📅 ประกาศงบอีก {days_to_earnings} วัน'
        except Exception:
            pass

        # -- Earnings Quality: FCF + Revenue Growth Consistency -----------------
        fcf_positive  = False
        rev_growing   = False
        quality_score = 0
        try:
            cashflow = t.quarterly_cashflow
            if cashflow is not None and not cashflow.empty:
                fcf_row = None
                for row_name in ['Free Cash Flow', 'FreeCashFlow']:
                    if row_name in cashflow.index:
                        fcf_row = row_name
                        break
                if fcf_row:
                    recent_fcf = cashflow.loc[fcf_row].head(4).dropna()
                    if len(recent_fcf) >= 2:
                        fcf_positive = all(float(v) > 0 for v in recent_fcf)
        except Exception:
            pass

        try:
            financials = t.quarterly_financials
            if financials is not None and not financials.empty:
                rev_row = None
                for row_name in ['Total Revenue', 'TotalRevenue']:
                    if row_name in financials.index:
                        rev_row = row_name
                        break
                if rev_row:
                    revs = financials.loc[rev_row].head(5).dropna()
                    if len(revs) >= 2:
                        rev_growing = float(revs.iloc[0]) > float(revs.iloc[1])
        except Exception:
            pass

        if fcf_positive: quality_score += 1
        if rev_growing:  quality_score += 1

        details = {
            'roe':             round(roe * 100, 2),
            'debt_equity':     round(de / 100, 2),
            'profit_margin':   round(margin * 100, 2),
            'div_yield':       round(div * 100, 2),
            'pe_ratio':        round(pe_ratio, 2),
            'forward_pe':      round(forward_pe, 2),
            'peg_ratio':       round(peg_ratio, 2),
            'pb_ratio':        round(pb_ratio, 2),
            'rev_growth':      round(rev_growth * 100, 2),
            'earnings_growth': round(earnings_growth * 100, 2),
            'valuation_flag':  valuation_flag,
            'valuation_score': val_score,
            'sector':          sector,
            # -- Analyst --
            'analyst_rec':    recommendation,
            'target_price':   round(target_price, 2),
            'upside_pct':     round(upside_pct, 1),
            'num_analysts':   num_analysts,
            'analyst_score':  analyst_score,
            # -- Earnings Calendar --
            'days_to_earnings': days_to_earnings,
            'earnings_warning': earnings_warning,
            # -- Quality --
            'fcf_positive':  fcf_positive,
            'rev_growing':   rev_growing,
            'quality_score': quality_score,
        }
        return passed, details

    except Exception as e:
        log.debug(f'ดึงข้อมูลงบ {ticker} ล้มเหลว: {e}')
        return False, {
            'roe': 0, 'debt_equity': 0, 'profit_margin': 0, 'div_yield': 0,
            'pe_ratio': 0, 'forward_pe': 0, 'peg_ratio': 0, 'pb_ratio': 0,
            'rev_growth': 0, 'earnings_growth': 0, 'valuation_flag': 'unknown',
            'valuation_score': 0, 'sector': 'Unknown',
            'analyst_rec': 'none', 'target_price': 0, 'upside_pct': 0,
            'num_analysts': 0, 'analyst_score': 0,
            'days_to_earnings': None, 'earnings_warning': '',
            'fcf_positive': False, 'rev_growing': False, 'quality_score': 0,
        }


# ==============================================================================
