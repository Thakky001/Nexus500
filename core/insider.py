import yfinance as yf
import pandas as pd
from datetime import datetime, timezone, timedelta
from config import INSIDER_LOOKBACK_DAYS
from logger import log


def check_insider_activity(ticker: str) -> dict:
    """
    ดึง Insider Transactions ย้อนหลัง INSIDER_LOOKBACK_DAYS วัน
    แล้วนับ Purchase vs Sale

    Return dict:
      net_action:    'buying' | 'selling' | 'neutral'
      buy_count:     int
      sell_count:    int
      insider_score: 0 หรือ 1  (1 = Net Buying)
      summary:       str (ข้อความสั้น)
    """
    default = {
        'net_action':    'neutral',
        'buy_count':     0,
        'sell_count':    0,
        'insider_score': 0,
        'summary':       'ไม่มีข้อมูล Insider',
    }

    try:
        t = yf.Ticker(ticker)
        txn = t.insider_transactions

        if txn is None or txn.empty:
            return default

        # ── กรองเฉพาะ N วันล่าสุด ──────────────────────────────────
        cutoff = datetime.now(timezone.utc) - timedelta(days=INSIDER_LOOKBACK_DAYS)

        # yfinance คืนคอลัมน์ 'Start Date' หรือ 'Date' ขึ้นอยู่กับเวอร์ชัน
        date_col = None
        for col in ['Start Date', 'Date', 'startDate']:
            if col in txn.columns:
                date_col = col
                break

        if date_col:
            txn[date_col] = pd.to_datetime(txn[date_col], utc=True, errors='coerce')
            txn = txn[txn[date_col] >= cutoff]

        if txn.empty:
            return default

        # ── นับ Buy vs Sell ─────────────────────────────────────────
        text_col = None
        for col in ['Transaction', 'Text', 'transaction']:
            if col in txn.columns:
                text_col = col
                break

        buy_count  = 0
        sell_count = 0

        if text_col:
            for val in txn[text_col].dropna():
                val_lower = str(val).lower()
                if 'purchase' in val_lower or 'buy' in val_lower or 'acquisition' in val_lower:
                    buy_count += 1
                elif 'sale' in val_lower or 'sell' in val_lower or 'disposition' in val_lower:
                    sell_count += 1
        else:
            # Fallback: ดูจากคอลัมน์ Shares (ถ้า negative = ขาย)
            shares_col = None
            for col in ['Shares', 'shares']:
                if col in txn.columns:
                    shares_col = col
                    break
            if shares_col:
                for val in txn[shares_col].dropna():
                    try:
                        v = float(str(val).replace(',', ''))
                        if v > 0:
                            buy_count += 1
                        elif v < 0:
                            sell_count += 1
                    except ValueError:
                        pass

        # ── ตัดสิน Net Action ───────────────────────────────────────
        if buy_count > sell_count:
            net_action    = 'buying'
            insider_score = 1
            summary       = f'🟢 Insider ซื้อสุทธิ ({buy_count}B / {sell_count}S ใน {INSIDER_LOOKBACK_DAYS}d)'
        elif sell_count > buy_count and sell_count > 3:
            net_action    = 'selling'
            insider_score = -1      # ขายหนัก (>3 ครั้ง) → -1 (penalty!)
            summary       = f'🔴 Insider ขายหนัก! ({buy_count}B / {sell_count}S ใน {INSIDER_LOOKBACK_DAYS}d)'
        elif sell_count > buy_count:
            net_action    = 'selling'
            insider_score = 0       # ขายแต่ไม่หนัก → 0
            summary       = f'🔴 Insider ขายสุทธิ ({buy_count}B / {sell_count}S ใน {INSIDER_LOOKBACK_DAYS}d)'
        else:
            net_action    = 'neutral'
            insider_score = 0
            summary       = f'⚪ Insider Neutral ({buy_count}B / {sell_count}S ใน {INSIDER_LOOKBACK_DAYS}d)'

        log.debug(f'[Insider] {ticker}: {summary}')

        return {
            'net_action':    net_action,
            'buy_count':     buy_count,
            'sell_count':    sell_count,
            'insider_score': insider_score,
            'summary':       summary,
        }

    except Exception as e:
        log.debug(f'[Insider] ดึงข้อมูล {ticker} ล้มเหลว: {e}')
        return default
