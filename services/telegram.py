import requests
from config import *
from logger import log

# ==============================================================================
def send_telegram(message: str) -> bool:
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage'
    payload = {
        'chat_id': TELEGRAM_CHAT_ID, 'text': message,
        'parse_mode': 'HTML', 'disable_web_page_preview': True,
    }
    try:
        resp = requests.post(url, json=payload, timeout=10)
        resp.raise_for_status()
        return True
    except Exception as e:
        log.error(f'ส่ง Telegram ล้มเหลว: {e}')
        return False


def fmt_vol(vol: int) -> str:
    if vol >= 1_000_000_000: return f'{vol/1_000_000_000:.1f}B'
    if vol >= 1_000_000:     return f'{vol/1_000_000:.1f}M'
    return f'{vol:,}'


def score_bar(score: int) -> str:
    return f'{"█" * score}{"░" * (10 - score)} {score}/10'


def build_message(stock: dict, headlines: list, confidence: float, rank: int = 0, sent_breakdown: dict = None) -> str:
    if sent_breakdown is None: sent_breakdown = {}
    s   = stock['score']
    t   = stock['ticker']
    bar = score_bar(s)

    rank_label = f'  #{rank} TODAY\'S TOP' if rank else ''

    if s >= 9:   badge = f'🏆 ELITE{rank_label}'
    elif s >= 8: badge = f'🥇 STRONG{rank_label}'
    elif s >= 7: badge = f'🥈 GOOD{rank_label}'
    else:        badge = f'🥉 WATCH{rank_label}'

    bonuses = []
    if stock.get('bonus_adx'):       bonuses.append('⚡ ADX มีเทรนด์แข็งแกร่ง')
    if stock.get('bonus_rsi'):       bonuses.append('🎯 RSI โซนเก็บของ')
    if stock.get('bonus_vol_surge'): bonuses.append('📣 มีแรงซื้อผิดปกติ')
    if stock.get('pass_52w'):        bonuses.append('🏔 โครงสร้างราคายกตัว')
    if stock.get('valuation_flag') == 'cheap': bonuses.append('💸 Valuation ค่อนข้างถูก')
    if stock.get('rs_vs_spy', 0) > 0: bonuses.append(f'📈 RS vs SPY {stock["rs_vs_spy"]:+.1f}%')
    bonus_line = '  '.join(bonuses) if bonuses else '—'

    news_lines = ''.join(f'  {i}. {h}\n' for i, h in enumerate(headlines, 1))
    conf_pct   = f'{confidence*100:.0f}%'

    val_score    = stock.get('valuation_score', 0)
    analyst_sc   = stock.get('analyst_score', 0)
    quality_sc   = stock.get('quality_score', 0)
    rs_bonus     = stock.get('rs_bonus', 0)
    insider_sc   = stock.get('insider_score', 0)
    streak_bonus = stock.get('streak_bonus', 0)
    composite    = round(
        s + val_score + analyst_sc + quality_sc + rs_bonus + insider_sc + streak_bonus + confidence,
        2
    )

    # -- Timing Signal -----------------------------------------------------------
    timing = stock.get('timing_signal', '—')

    # -- Analyst Section ---------------------------------------------------------
    analyst_rec = stock.get('analyst_rec', 'none')
    target_p    = stock.get('target_price', 0)
    upside      = stock.get('upside_pct', 0)
    n_analysts  = stock.get('num_analysts', 0)
    analyst_line = (
        f'  • Rating: {analyst_rec.upper()} ({n_analysts} Analysts)\n'
        f'  • Target Price: ${target_p} (Upside {upside:+.1f}%)\n'
        if target_p > 0 else '  • ไม่มีข้อมูล Analyst\n'
    )

    # -- Earnings Warning --------------------------------------------------------
    earn_warn = stock.get('earnings_warning', '')
    earn_line = f'\n{earn_warn}\n' if earn_warn else ''

    # -- Earnings Quality --------------------------------------------------------
    fcf_icon = '✅' if stock.get('fcf_positive') else '❌'
    rev_icon = '✅' if stock.get('rev_growing') else '❌'

    # -- Historical Consistency --------------------------------------------------
    streak = stock.get('appearance_streak', 0)
    streak_line = (
        f'  • ปรากฏในผลสแกน {streak}/{STREAK_LOOKBACK_DAYS} วัน (Bonus +{streak_bonus})\n'
    )

    # -- Insider Activity --------------------------------------------------------
    insider_summary = stock.get('insider_summary', 'ไม่มีข้อมูล Insider')

    return (
        f'📈 <b>${t}</b>  {badge} (Long-term)\n'
        f'<code>{bar}</code>\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'💲 <b>ราคาปัจจุบัน</b>  ${stock.get("price", 0)}\n'
        f'📊 <b>EMA 20/50/200</b>  ${stock.get("ema20", 0)} / ${stock.get("ema50", 0)} / ${stock.get("ema200", 0)}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🚦 <b>Timing Signal:</b> {timing}\n'
        f'   ห่าง EMA20: {stock.get("pct_above_ema20", 0):+.1f}% | RS vs SPY: {stock.get("rs_vs_spy", 0):+.1f}%\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🏢 <b>Fundamentals (ความแข็งแกร่ง)</b>\n'
        f'  • ROE: {stock.get("roe", 0):.1f}%\n'
        f'  • Net Margin: {stock.get("profit_margin", 0):.1f}%\n'
        f'  • D/E Ratio: {stock.get("debt_equity", 0):.2f}x\n'
        f'  • Div Yield: {stock.get("div_yield", 0):.2f}%\n'
        f'  • P/E Ratio: {stock.get("pe_ratio", 0):.1f}x ({stock.get("valuation_flag", "")})\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🎯 <b>Analyst Consensus</b>\n'
        f'{analyst_line}'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'📈 <b>Earnings Quality</b>\n'
        f'  • FCF (4Q): {fcf_icon} {"บวกทุกไตรมาส" if stock.get("fcf_positive") else "ไม่สม่ำเสมอ"}\n'
        f'  • Revenue QoQ: {rev_icon} {"เติบโต" if stock.get("rev_growing") else "ลดลง/หยุดนิ่ง"}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'👥 <b>Insider Activity (90d)</b>\n'
        f'  {insider_summary}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🔁 <b>Historical Consistency</b>\n'
        f'{streak_line}'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'💹 <b>Sector Money Flow (1M)</b>\n'
        f'  • {stock.get("sector", "Unknown")}: {stock.get("sector_flow", 0.0):+.1f}%\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🔢 <b>Technical Stats</b>\n'
        f'  • RSI(14): {stock["rsi"]} | MACD Hist: {stock["macd_hist"]:+.4f}\n'
        f'  • ห่าง 52W High: -{stock["pct_from_52w"]:.1f}%\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🎯 <b>Accumulation Zones (Fibonacci)</b>\n\n'
        f'  ▶️ <b>ไม้แรก (ราคาปัจจุบัน)</b> : <code>${stock["price"]}</code>\n'
        f'  ▶️ <b>ย่อเบา (Fib 23.6%)</b>   : <code>${stock.get("entry_fib_236", 0)}</code>\n'
        f'  ▶️ <b>ย่อปกติ (Fib 38.2%)</b>  : <code>${stock.get("entry_fib_382", 0)}</code>\n'
        f'  ▶️ <b>ย่อแรง (Fib 50.0%)</b>   : <code>${stock.get("entry_fib_500", 0)}</code>\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🛡️ <b>Exit Strategy</b>\n'
        f'  • Stop Loss (EMA200-3%) : ${stock.get("stop_loss", 0)}\n'
        f'  • Trailing Stop (2xATR) : ${stock.get("trail_stop", 0)}\n'
        f'  • Take Profit (+30%)    : ${stock.get("take_profit", 0)}\n'
        f'  • Risk/Reward Ratio     : 1:{stock.get("rr_ratio", 0)}\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'💰 <b>Position Sizing (พอร์ต ${PORTFOLIO_VALUE:,})</b>\n'
        f'  • จำนวนหุ้นแนะนำ  : {stock.get("position_shares", 0)} หุ้น\n'
        f'  • เงินลงทุน        : ${stock.get("position_amount", 0):,.2f} ({stock.get("pct_portfolio", 0)}%)\n'
        f'  • ความเสี่ยงสูงสุด  : ${stock.get("position_risk", 0):,.2f} ({MAX_RISK_PER_TRADE}%)\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'✨ <b>Signals:</b> {bonus_line}\n'
        f'{earn_line}'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'📰 <b>ข่าว (🟢 Positive {conf_pct})</b>\n'
        f'  📊 Breakdown: {sent_breakdown.get("positive", 0)} Pos | {sent_breakdown.get("negative", 0)} Neg | {sent_breakdown.get("neutral", 0)} Neu\n'
        f'{news_lines}'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'⭐ <b>Composite Score</b>: {composite:.2f}  \n'
        f'<i>(Tech {s}/11 + Val {val_score}/3 + Analyst {analyst_sc}/3 + Quality {quality_sc}/2 + Insider {insider_sc} + Streak {streak_bonus} + Flow {stock.get("sector_flow_score", 0)} + Sent {conf_pct})</i>\n'
    )
