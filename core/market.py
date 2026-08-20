import yfinance as yf
import pandas_ta_classic as ta
from config import (
    REGIME_BULL_MIN_SCORE, REGIME_CAUTION_MIN_SCORE, REGIME_BEAR_MIN_SCORE,
    REGIME_BULL_RSI, REGIME_CAUTION_RSI, REGIME_BEAR_RSI
)
from logger import log


def detect_market_regime() -> dict:
    """
    ดึงข้อมูล SPY 1 ปีย้อนหลัง แล้วตรวจสภาพตลาดรวม:
      - SPY price vs EMA200
      - SPY RSI(14)
      - 5-day return (momentum)

    Return dict:
      regime: 'bull' | 'caution' | 'bear'
      adjusted_min_score: int
      spy_price: float
      spy_ema200: float
      spy_rsi: float
      spy_5d_return: float
      label: str (ข้อความอ่านง่าย)
    """
    default = {
        'regime': 'bull',
        'adjusted_min_score': REGIME_BULL_MIN_SCORE,
        'spy_price': 0.0,
        'spy_ema200': 0.0,
        'spy_rsi': 50.0,
        'spy_5d_return': 0.0,
        'label': '🟢 Bull (Default — ดึง SPY ไม่สำเร็จ)',
        'rsi_range': REGIME_BULL_RSI,
    }

    df = None
    for attempt in range(3):
        try:
            df = yf.download(
                'SPY', period='1y', interval='1d',
                auto_adjust=True, progress=False, threads=False,
            )
            if df is not None and not df.empty and len(df) >= 210:
                if hasattr(df.columns, 'levels'):
                    df.columns = df.columns.get_level_values(0)
                break
        except Exception as e:
            log.debug(f"[Market Regime] SPY attempt {attempt+1} failed: {e}")
        
        import time
        time.sleep(5)  # รอ 5 วินาทีให้ yfinance รีเซ็ตคุกกี้

    if df is None or len(df) < 210:
        log.warning('[Market Regime] ข้อมูล SPY ไม่พอ (ลอง 3 ครั้งแล้ว) — ใช้ค่าเริ่มต้น Bull')
        return default

    try:
        close   = df['Close']
        high    = df['High']
        low     = df['Low']

        ema200  = ta.ema(close, length=200)
        rsi     = ta.rsi(close, length=14)

        price      = float(close.iloc[-1].iloc[0] if hasattr(close.iloc[-1], 'iloc') else close.iloc[-1])
        e200       = float(ema200.iloc[-1].iloc[0] if hasattr(ema200.iloc[-1], 'iloc') else ema200.iloc[-1])
        rsi_val    = float(rsi.iloc[-1].iloc[0] if hasattr(rsi.iloc[-1], 'iloc') else rsi.iloc[-1])
        price_5d   = float(close.iloc[-6].iloc[0] if hasattr(close.iloc[-6], 'iloc') else close.iloc[-6]) if len(close) >= 6 else price
        ret_5d     = ((price - price_5d) / price_5d * 100) if price_5d > 0 else 0.0

        # ── ตัดสิน Regime ─────────────────────────────────────────
        pct_vs_e200 = ((price - e200) / e200 * 100) if e200 > 0 else 0.0

        if price < e200:
            # SPY ต่ำกว่า EMA200 = ขาลงชัดเจน
            regime = 'bear'
            adj_score = REGIME_BEAR_MIN_SCORE
            rsi_range = REGIME_BEAR_RSI
            label = f'🔴 Bear (SPY ${price:.1f} < EMA200 ${e200:.1f})'
        elif pct_vs_e200 < 2.0 or rsi_val < 40:
            # SPY อยู่ใกล้ EMA200 หรือ RSI ต่ำ = ระวัง
            regime = 'caution'
            adj_score = REGIME_CAUTION_MIN_SCORE
            rsi_range = REGIME_CAUTION_RSI
            label = f'🟡 Caution (SPY ใกล้ EMA200 | RSI {rsi_val:.0f})'
        else:
            regime = 'bull'
            adj_score = REGIME_BULL_MIN_SCORE
            rsi_range = REGIME_BULL_RSI
            label = f'🟢 Bull (SPY ${price:.1f} > EMA200 ${e200:.1f} | RSI {rsi_val:.0f})'

        log.info(f'[Market Regime] {label} → MIN_SCORE = {adj_score}')

        return {
            'regime': regime,
            'adjusted_min_score': adj_score,
            'spy_price': round(price, 2),
            'spy_ema200': round(e200, 2),
            'spy_rsi': round(rsi_val, 1),
            'spy_5d_return': round(ret_5d, 2),
            'label': label,
            'rsi_range': rsi_range,
        }

    except Exception as e:
        log.error(f'[Market Regime] ดึงข้อมูล SPY ล้มเหลว: {e} — ใช้ค่าเริ่มต้น Bull')
        return default
