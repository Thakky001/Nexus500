"""
Nexus500 Backtesting Engine
วิเคราะห์ประสิทธิภาพย้อนหลังของ Signal ที่บันทึกใน Google Sheets
"""
import time
from datetime import datetime, timedelta, timezone
import yfinance as yf
from logger import log


def backtest_signals(lookback_days: int = 90) -> dict:
    """
    ดึง Signal ย้อนหลังจาก Google Sheets แล้วคำนวณ Forward Returns

    Parameters
    ----------
    lookback_days : int
        จำนวนวันย้อนหลัง (default 90 วัน)

    Returns
    -------
    dict ที่ประกอบด้วย:
      total_signals   : จำนวน Signal ทั้งหมด
      win_rate        : % ของ Signal ที่ให้ผลตอบแทนบวก (30 วัน)
      avg_return_30d  : ผลตอบแทนเฉลี่ย 30 วัน (%)
      best_return     : ผลตอบแทนดีที่สุด (%)
      worst_return    : ผลตอบแทนแย่ที่สุด (%)
      profit_factor   : Gross Profit / Gross Loss
      stop_hit_rate   : % ที่ Stop Loss ถูก Hit
      tp_hit_rate     : % ที่ Take Profit ถูก Hit
      by_period       : Forward returns แยกตามช่วงเวลา (7/14/30/90 วัน)
      by_label        : ผล Backtest แยกตาม Sentiment Label
      details         : รายละเอียดแต่ละ Signal
    """
    from services.sheets import get_scan_history
    history = get_scan_history(days=lookback_days)

    if not history:
        return {
            "error": "ไม่มีข้อมูลย้อนหลังใน Google Sheets",
            "total_signals": 0,
        }

    results = []
    hold_periods = [7, 14, 30, 90]

    for signal in history:
        ticker     = signal.get('ticker', '')
        entry_date = signal.get('date', '')
        entry_price = signal.get('price')
        stop_loss   = signal.get('stop_loss')
        take_profit = signal.get('take_profit')
        sent_label  = signal.get('sentiment', 'positive')  # รองรับ label ใหม่

        # ข้ามถ้าข้อมูลไม่ครบ
        if not ticker or not entry_date or not entry_price:
            continue
        try:
            entry_price = float(entry_price)
            if entry_price <= 0:
                continue
        except (ValueError, TypeError):
            continue

        # คำนวณวันสิ้นสุด
        try:
            start_dt = datetime.strptime(entry_date, '%Y-%m-%d')
        except ValueError:
            continue
        end_dt   = start_dt + timedelta(days=max(hold_periods) + 15)
        end_str  = end_dt.strftime('%Y-%m-%d')

        try:
            df = yf.download(
                ticker,
                start=entry_date,
                end=end_str,
                auto_adjust=True,
                progress=False,
                threads=False,
            )
            if df is None or df.empty or len(df) < 2:
                log.debug(f"[Backtest] {ticker}: ไม่มีข้อมูล ({entry_date})")
                continue

            # Flatten multi-index ถ้ามี
            if hasattr(df.columns, 'levels'):
                df.columns = df.columns.get_level_values(0)

            close_arr = df['Close'].values
            high_arr  = df['High'].values
            low_arr   = df['Low'].values

            # ── Forward Returns ──────────────────────────────────────
            forward_returns = {}
            for days in hold_periods:
                if len(close_arr) > days:
                    future_price = float(close_arr[days])
                    ret = (future_price / entry_price - 1) * 100
                    forward_returns[f'{days}d'] = round(ret, 2)

            # ── Stop Loss / Take Profit Hit Check ────────────────────
            stop_hit_day = None
            tp_hit_day   = None

            if stop_loss and take_profit:
                try:
                    sl = float(stop_loss)
                    tp = float(take_profit)
                    for i in range(1, len(df)):
                        if sl > 0 and float(low_arr[i]) <= sl and stop_hit_day is None:
                            stop_hit_day = i
                        if tp > 0 and float(high_arr[i]) >= tp and tp_hit_day is None:
                            tp_hit_day = i
                except (ValueError, TypeError):
                    pass

            ret_30d = forward_returns.get('30d', None)
            results.append({
                'ticker':          ticker,
                'entry_date':      entry_date,
                'entry_price':     entry_price,
                'composite_score': signal.get('composite', 0),
                'sentiment_label': sent_label,
                'forward_returns': forward_returns,
                'stop_hit_day':    stop_hit_day,
                'tp_hit_day':      tp_hit_day,
                'won':             (ret_30d > 0) if ret_30d is not None else None,
            })

        except Exception as e:
            log.debug(f"[Backtest] {ticker} ({entry_date}) error: {e}")

    # ── คำนวณ Aggregate Metrics ──────────────────────────────────────────────
    if not results:
        return {
            "error": "ไม่สามารถดึงข้อมูลราคาย้อนหลังได้",
            "total_signals": 0,
        }

    decided = [r for r in results if r['won'] is not None]
    wins    = [r for r in decided if r['won']]
    losses  = [r for r in decided if not r['won']]

    # Forward returns by period
    by_period = {}
    for days in hold_periods:
        key = f'{days}d'
        period_returns = [r['forward_returns'][key]
                          for r in results if key in r['forward_returns']]
        if period_returns:
            wins_p  = [x for x in period_returns if x > 0]
            by_period[key] = {
                'count':        len(period_returns),
                'avg_return':   round(sum(period_returns) / len(period_returns), 2),
                'win_rate':     round(len(wins_p) / len(period_returns) * 100, 1),
                'best':         round(max(period_returns), 2),
                'worst':        round(min(period_returns), 2),
            }

    # Profit Factor
    returns_30d = [r['forward_returns']['30d']
                   for r in results if '30d' in r['forward_returns']]
    gross_profit = sum(x for x in returns_30d if x > 0)
    gross_loss   = abs(sum(x for x in returns_30d if x < 0))
    profit_factor = round(gross_profit / gross_loss, 2) if gross_loss > 0 else None

    # By sentiment label (รองรับ label ใหม่: positive/neutral/negative)
    by_label = {}
    for label in ['positive', 'neutral', 'negative']:
        label_results = [r for r in results
                         if r.get('sentiment_label') == label
                         and '30d' in r['forward_returns']]
        if label_results:
            label_returns = [r['forward_returns']['30d'] for r in label_results]
            by_label[label] = {
                'count':      len(label_results),
                'avg_return': round(sum(label_returns) / len(label_returns), 2),
                'win_rate':   round(
                    sum(1 for x in label_returns if x > 0) / len(label_results) * 100, 1
                ),
            }

    return {
        'total_signals':    len(results),
        'win_rate':         round(len(wins) / len(decided) * 100, 1) if decided else 0,
        'avg_return_30d':   round(sum(returns_30d) / len(returns_30d), 2) if returns_30d else 0,
        'best_return':      round(max(returns_30d), 2) if returns_30d else 0,
        'worst_return':     round(min(returns_30d), 2) if returns_30d else 0,
        'profit_factor':    profit_factor,
        'stop_hit_rate':    round(
            sum(1 for r in results if r['stop_hit_day']) / len(results) * 100, 1
        ),
        'tp_hit_rate':      round(
            sum(1 for r in results if r['tp_hit_day']) / len(results) * 100, 1
        ),
        'by_period':        by_period,
        'by_label':         by_label,
        'details':          results,
        'lookback_days':    lookback_days,
        'generated_at':     datetime.now(timezone.utc).isoformat(),
    }
