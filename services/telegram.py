import requests
from config import *
from logger import log

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


def build_message(stock: dict, headlines: list, confidence: float, rank: int = 0, sent_breakdown: dict = None) -> str:
    if sent_breakdown is None: sent_breakdown = {}
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
    if stock.get("valuation_flag") == "cheap": bonuses.append("💸 Valuation ค่อนข้างถูก")
    bonus_line = "  ".join(bonuses) if bonuses else "—"

    news_lines = "".join(f"  {i}. {h}\n" for i, h in enumerate(headlines, 1))
    conf_pct   = f"{confidence*100:.0f}%"
    
    val_score = stock.get("valuation_score", 0)
    composite = round(stock["score"] + val_score + confidence, 2)

    return (
        f"📈 <b>${t}</b>  {badge} (Long-term)\n"
        f"<code>{bar}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💲 <b>ราคาปัจจุบัน</b>  ${stock['price']:,.2f}\n"
        f"📊 <b>EMA 20/50/200</b>  "
        f"${stock['ema20']:,.2f} / ${stock['ema50']:,.2f} / ${stock['ema200']:,.2f}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏢 <b>Fundamentals (ความแข็งแกร่ง)</b>\n"
        f"  • ROE: {stock.get('roe', 0):.1f}%\n"
        f"  • Net Margin: {stock.get('profit_margin', 0):.1f}%\n"
        f"  • D/E Ratio: {stock.get('debt_equity', 0):.2f}x\n"
        f"  • Div Yield: {stock.get('div_yield', 0):.2f}%\n"
        f"  • P/E Ratio: {stock.get('pe_ratio', 0):.1f}x ({stock.get('valuation_flag', '')})\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🔢 <b>Technical Stats</b>\n"
        f"  • RSI(14): {stock['rsi']} | MACD Hist: {stock['macd_hist']:+.4f}\n"
        f"  • ห่าง 52W High: -{stock['pct_from_52w']:.1f}%\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🎯 <b>Accumulation Zones (Fibonacci)</b>\n\n"
        f"  ▶️ <b>ไม้แรก (ราคาปัจจุบัน)</b> : <code>${stock.get('entry_current', 0):,.2f}</code>\n"
        f"  ▶️ <b>ย่อเบา (Fib 23.6%)</b>   : <code>${stock.get('entry_fib_236', 0):,.2f}</code>\n"
        f"  ▶️ <b>ย่อปกติ (Fib 38.2%)</b>  : <code>${stock.get('entry_fib_382', 0):,.2f}</code>\n"
        f"  ▶️ <b>ย่อแรง (Fib 50.0%)</b>   : <code>${stock.get('entry_fib_500', 0):,.2f}</code>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>Exit Strategy</b>\n"
        f"  • Stop Loss (EMA200-3%) : ${stock.get('stop_loss', 0):,.2f}\n"
        f"  • Trailing Stop (2xATR) : ${stock.get('trail_stop', 0):,.2f}\n"
        f"  • Take Profit (+30%)    : ${stock.get('take_profit', 0):,.2f}\n"
        f"  • Risk/Reward Ratio     : 1:{stock.get('rr_ratio', 0)}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"💰 <b>Position Sizing (พอร์ต ${PORTFOLIO_VALUE:,.0f})</b>\n"
        f"  • จำนวนหุ้นแนะนำ  : {stock.get('position_shares', 0)} หุ้น\n"
        f"  • เงินลงทุน        : ${stock.get('position_amount', 0):,.2f} ({stock.get('pct_portfolio', 0)}%)\n"
        f"  • ความเสี่ยงสูงสุด  : ${stock.get('position_risk', 0):,.2f} ({MAX_RISK_PER_TRADE}%)\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"✨ <b>Signals:</b> {bonus_line}\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"📰 <b>ข่าว (🟢 Positive {conf_pct})</b>\n"
        f"  📊 Breakdown: {sent_breakdown.get('positive', 0)} Pos | {sent_breakdown.get('negative', 0)} Neg | {sent_breakdown.get('neutral', 0)} Neu\n"
        f"{news_lines}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"⭐ <b>Composite Score</b>: {composite:.2f}  "
        f"<i>(Tech {stock['score']}/10 + Val {val_score}/3 + Sentiment {conf_pct})</i>\n"
    )


