import time
from datetime import datetime, timezone
from config import *
from logger import log

from core.technical import get_all_us_tickers, fetch_and_filter, reset_spy_cache
from core.fundamental import check_fundamentals
from core.sentiment import fetch_news, analyze_sentiment
from core.market import detect_market_regime
from core.insider import check_insider_activity
from services.telegram import send_telegram, build_message
from services.sheets import save_to_sheet, get_ticker_streak


def diversify_results(results: list, max_per_sector: int = MAX_PER_SECTOR) -> list:
    """กรองหุ้นไม่ให้กระจุกตัวใน Sector เดียวกันมากเกินไป"""
    final_list   = []
    sector_counts = {}

    for item in results:
        stock  = item[0]
        sector = stock.get('sector', 'Unknown')

        if sector_counts.get(sector, 0) < max_per_sector:
            final_list.append(item)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        if len(final_list) >= TOP_N:
            break

    return final_list

# ==============================================================================
#  งานหลัก — Background Thread
# ==============================================================================
def run_scan():
    """ฟังก์ชันหลักที่รันใน Background Thread"""
    log.info('==========================================')
    log.info('  1000 STOCK LONG-TERM SCANNER เริ่มงาน')
    log.info('==========================================')

    # ล้าง SPY cache เพื่อเริ่ม scan รอบใหม่
    reset_spy_cache()

    scan_date = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    # ── Step 0: ตรวจ Market Regime ────────────────────────────────────────
    regime = detect_market_regime()
    effective_min_score = regime['adjusted_min_score']

    send_telegram(
        f'🌍 <b>Market Regime</b>\n'
        f'{regime["label"]}\n'
        f'MIN_SCORE วันนี้: <b>{effective_min_score}/10</b>\n'
        f'SPY RSI: {regime["spy_rsi"]} | 5d Return: {regime["spy_5d_return"]:+.1f}%\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🔍 <i>เริ่มสแกนหุ้นทั้งหมด...</i>'
    )

    # ── Step 1: ดึงรายชื่อหุ้น ────────────────────────────────────────────
    tickers = get_all_us_tickers()
    if not tickers:
        return

    # ── Step 2: Technical Screening ───────────────────────────────────────
    log.info(f'[Market] {regime["label"]} → MIN_SCORE = {effective_min_score}')
    rsi_lo, rsi_hi = regime.get('rsi_range', (RSI_LOW, RSI_HIGH))
    candidates = fetch_and_filter(tickers, min_score=effective_min_score, rsi_low=rsi_lo, rsi_high=rsi_hi)
    if not candidates:
        send_telegram(
            f'🔍 <b>Long-Term Scanner</b>\n\n'
            f'ไม่มีหุ้นผ่านเกณฑ์กราฟวันนี้ 📭\n'
            f'<i>(เกณฑ์: Score >= {effective_min_score}/10 | Regime: {regime["regime"].upper()})</i>'
        )
        return

    # ── Step 2.5: Fundamental Filter ──────────────────────────────────────
    fund_passed = []
    for stock in candidates:
        ticker = stock['ticker']
        log.info(f'ตรวจงบการเงิน {ticker}...')
        passed, fund_details = check_fundamentals(ticker)
        if passed:
            stock.update(fund_details)
            fund_passed.append(stock)
        time.sleep(0.5)

    if not fund_passed:
        send_telegram('ผ่านกราฟแต่ไม่มีหุ้นตัวไหนผ่านเกณฑ์งบการเงินวันนี้ 📭')
        return

    # ── Step 2.7: Insider Activity ────────────────────────────────────────
    for stock in fund_passed:
        ticker = stock['ticker']
        log.info(f'ตรวจ Insider {ticker}...')
        insider = check_insider_activity(ticker)
        stock['insider_action'] = insider['net_action']
        stock['insider_score']  = insider['insider_score']
        stock['insider_summary'] = insider['summary']
        time.sleep(0.3)

    # ── Step 2.8: Historical Consistency (Appearance Streak) ──────────────
    for stock in fund_passed:
        ticker = stock['ticker']
        streak = get_ticker_streak(ticker, lookback_days=STREAK_LOOKBACK_DAYS)
        streak_bonus = min(streak, MAX_STREAK_BONUS)
        stock['appearance_streak'] = streak
        stock['streak_bonus']      = streak_bonus

    # ── Step 2.9: Sector Money Flow ───────────────────────────────────────
    from core.market_context import get_sector_flows
    sector_flows = get_sector_flows()
    for stock in fund_passed:
        sector = stock.get('sector', 'Unknown')
        flow = sector_flows.get(sector, 0.0)
        stock['sector_flow'] = flow
        # ถ้า <= -5% คือไหลออกให้ -1, ถ้า >= 5% ไหลเข้าให้ +1
        stock['sector_flow_score'] = -1 if flow <= -SECTOR_FLOW_THRESHOLD else (1 if flow >= SECTOR_FLOW_THRESHOLD else 0)

    # ── Step 3-4: News + Sentiment ────────────────────────────────────────
    positive_results = []
    for stock in fund_passed:
        ticker = stock['ticker']
        log.info(f'ดึงข่าว {ticker} (Score:{stock["score"]})...')
        time.sleep(NEWS_PAUSE)

        headlines = fetch_news(ticker)
        if not headlines:
            log.info(f'  {ticker}: ไม่มีข่าว → ข้าม')
            continue

        log.info(f'  {ticker}: ส่ง FinBERT ({len(headlines)} ข่าว)...')
        time.sleep(AI_PAUSE)

        label, confidence, sent_bk = analyze_sentiment(headlines)
        log.info(f'  {ticker}: {label} ({confidence*100:.0f}%)')

        if label == 'positive':
            val_score     = stock.get('valuation_score', 0)
            analyst_sc    = stock.get('analyst_score', 0)
            quality_sc    = stock.get('quality_score', 0)
            insider_sc    = stock.get('insider_score', 0)
            streak_bonus  = stock.get('streak_bonus', 0)
            sector_flow_sc = stock.get('sector_flow_score', 0)
            # Composite = Tech (มี RS อยู่แล้ว) + Val + Analyst + Quality + Insider + Streak + SectorFlow + Sentiment
            composite = (
                stock['score']
                + val_score
                + analyst_sc
                + quality_sc
                + insider_sc
                + streak_bonus
                + sector_flow_sc
                + confidence
            )
            positive_results.append((stock, headlines, confidence, composite, sent_bk))

    if not positive_results:
        send_telegram(
            f'🔍 <b>Long-Term Scanner</b>\n\n'
            f'ผ่านเกณฑ์กราฟ + งบการเงิน {len(fund_passed)} ตัว\n'
            f'แต่ไม่มีข่าว Positive วันนี้ 📭'
        )
        return

    positive_results.sort(key=lambda x: x[3], reverse=True)
    top_results  = diversify_results(positive_results)
    total_passed = len(positive_results)

    # ── บันทึกลง Google Sheets ────────────────────────────────────────────
    save_to_sheet(top_results, scan_date, regime['regime'])

    # ── Summary Leaderboard ───────────────────────────────────────────────
    rank_medals  = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
    summary_rows = ''
    for rank, (stock, headlines, confidence, composite, sent_bk) in enumerate(top_results):
        medal    = rank_medals[rank] if rank < len(rank_medals) else f'{rank+1}.'
        sent_pct = f'{confidence*100:.0f}%'
        timing   = stock.get('timing_signal', '')
        summary_rows += (
            f'{medal} <b></b>  '
            f'Tech:{stock["score"]}/10  Sentiment:{sent_pct}  {timing}\n'
            f'    RSI {stock["rsi"]} | ADX {stock["adx"]} | '
            f'RS vs SPY {stock.get("rs_vs_spy", 0):+.1f}%\n'
        )

    send_telegram(
        f'🚨 <b>LONG-TERM SCAN — TOP {TOP_N}</b> 🚨\n'
        f'จากหุ้น Positive ทั้งหมด {total_passed} ตัว '
        f'(ผ่านทั้งกราฟ + งบการเงิน {len(fund_passed)} ตัว)\n'
        f'<i>Regime: {regime["label"]} | MIN_SCORE: {effective_min_score}</i>\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'{summary_rows}'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🏆 ≥9  🥇 ≥8  🥈 ≥7  🥉 ≥6  (Technical Score)'
    )
    time.sleep(2)

    for rank, (stock, headlines, confidence, composite, sent_bk) in enumerate(top_results):
        ok = send_telegram(build_message(stock, headlines, confidence, rank + 1, sent_bk))
        log.info(
            f'ส่ง #{rank+1} {stock["ticker"]} '
            f'Tech:{stock["score"]} Sent:{confidence*100:.0f}% Composite:{composite:.2f} '
            f'→ {"✅" if ok else "❌"}'
        )
        time.sleep(3)

    log.info(f'  เสร็จสิ้น! ส่ง Top {len(top_results)} จาก {total_passed} ตัว Positive')


# ==============================================================================
