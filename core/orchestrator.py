import time
from datetime import datetime, timezone
from config import (
    TOP_N, MIN_SCORE, MAX_PER_SECTOR, MAX_STREAK_BONUS, STREAK_LOOKBACK_DAYS,
    RSI_LOW, RSI_HIGH, SECTOR_FLOW_THRESHOLD,
    WEIGHT_TECHNICAL, WEIGHT_VALUATION, WEIGHT_ANALYST, WEIGHT_QUALITY,
    WEIGHT_INSIDER, WEIGHT_STREAK, WEIGHT_SECTOR_FLOW,
    SENTIMENT_POSITIVE_BONUS, SENTIMENT_NEUTRAL_BONUS,
    SENTIMENT_NEGATIVE_PENALTY, SENTIMENT_NEGATIVE_REJECT_CONF,
    NEWS_PAUSE, AI_PAUSE,
)
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

    # แสดง Macro Indicators ใน Telegram header
    macro     = regime.get('macro', {})
    macro_vix = macro.get('vix')
    macro_10y = macro.get('yield_10y')
    macro_dxy = macro.get('dollar_idx')
    macro_warnings = macro.get('macro_warning', [])

    macro_line = ''
    if any(v is not None for v in [macro_vix, macro_10y, macro_dxy]):
        parts = []
        if macro_vix  is not None: parts.append(f'VIX {macro_vix:.1f}')
        if macro_10y  is not None: parts.append(f'10Y {macro_10y:.2f}%')
        if macro_dxy  is not None: parts.append(f'DXY {macro_dxy:.1f}')
        macro_line = 'มาโคร: ' + ' | '.join(parts) + '\n'
        if macro_warnings:
            macro_line += '\n'.join(macro_warnings) + '\n'

    send_telegram(
        f'🌍 <b>Market Regime</b>\n'
        f'{regime["label"]}\n'
        f'{macro_line}'
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

    # ── Step 3–4: News + Sentiment (Score Adjustment แทน Binary Gate) ──────
    scored_results = []
    for stock in fund_passed:
        ticker = stock['ticker']
        log.info(f'ดึงข่าว {ticker} (Score:{stock["score"]})...')
        time.sleep(NEWS_PAUSE)

        headlines = fetch_news(ticker)
        if not headlines:
            log.info(f'  {ticker}: ไม่มีข่าว → ใช้ Sentiment neutral (0 คะแนน)')
            label, confidence, sent_bk = 'neutral', 0.0, {'positive': 0, 'negative': 0, 'neutral': 0, 'ratio': 0.0}
        else:
            log.info(f'  {ticker}: ส่ง FinBERT ({len(headlines)} ข่าว)...')
            time.sleep(AI_PAUSE)
            label, confidence, sent_bk = analyze_sentiment(headlines)
            log.info(f'  {ticker}: {label} ({confidence*100:.0f}%)')

        # Safety net: ตัดหุ้นที่ข่าวลบมากจริงๆ ออก
        if label == 'negative' and confidence >= SENTIMENT_NEGATIVE_REJECT_CONF:
            log.info(
                f'  ❌ {ticker}: Strong Negative ({confidence*100:.0f}%) '
                f'≥ {SENTIMENT_NEGATIVE_REJECT_CONF*100:.0f}% → REJECT'
            )
            continue

        # ── Sentiment Score Adjustment ──────────────────────────────────
        if label == 'positive':
            sent_adj = SENTIMENT_POSITIVE_BONUS * confidence
        elif label == 'negative':
            sent_adj = SENTIMENT_NEGATIVE_PENALTY * confidence
        else:  # neutral
            sent_adj = SENTIMENT_NEUTRAL_BONUS

        val_score      = stock.get('valuation_score', 0)
        analyst_sc     = stock.get('analyst_score', 0)
        quality_sc     = stock.get('quality_score', 0)
        insider_sc     = stock.get('insider_score', 0)
        streak_bonus   = stock.get('streak_bonus', 0)
        sector_flow_sc = stock.get('sector_flow_score', 0)

        # ── Weighted Composite Score ──────────────────────────────────
        composite = (
            stock['score']   * WEIGHT_TECHNICAL
            + val_score      * WEIGHT_VALUATION
            + analyst_sc     * WEIGHT_ANALYST
            + quality_sc     * WEIGHT_QUALITY
            + insider_sc     * WEIGHT_INSIDER
            + streak_bonus   * WEIGHT_STREAK
            + sector_flow_sc * WEIGHT_SECTOR_FLOW
            + sent_adj
        )
        log.info(
            f'  ✅ {ticker}: label={label} sent_adj={sent_adj:+.2f} composite={composite:.2f} '
            f'(Tech:{stock["score"]*WEIGHT_TECHNICAL:.1f} '
            f'Val:{val_score*WEIGHT_VALUATION:.1f} '
            f'Qual:{quality_sc*WEIGHT_QUALITY:.1f})'
        )
        scored_results.append((stock, headlines, confidence, composite, sent_bk, label))

    if not scored_results:
        send_telegram(
            f'🔍 <b>Long-Term Scanner</b>\n\n'
            f'ผ่านเกณฑ์กราฟ + งบการเงิน {len(fund_passed)} ตัว\n'
            f'แต่ถูกตัด Strong Negative Sentiment หมด 💭'
        )
        return

    scored_results.sort(key=lambda x: x[3], reverse=True)
    top_results  = diversify_results(scored_results)
    total_passed = len(scored_results)

    # ── บันทึกลง Google Sheets ────────────────────────────────────────────
    save_to_sheet(top_results, scan_date, regime['regime'])

    # ── Summary Leaderboard ───────────────────────────────────────────
    rank_medals  = ['🥇', '🥈', '🥉', '4️⃣', '5️⃣']
    summary_rows = ''
    for rank, (stock, headlines, confidence, composite, sent_bk, sent_label) in enumerate(top_results):
        medal     = rank_medals[rank] if rank < len(rank_medals) else f'{rank+1}.'
        sent_pct  = f'{confidence*100:.0f}%'
        timing    = stock.get('timing_signal', '')
        sent_icon = '🟢' if sent_label == 'positive' else ('⚫' if sent_label == 'neutral' else '🔴')
        summary_rows += (
            f'{medal} <b>${stock["ticker"]}</b>  '
            f'Tech:{stock["score"]}/10  '
            f'{sent_icon}Sent:{sent_pct}  {timing}\n'
            f'    RSI {stock["rsi"]} | ADX {stock["adx"]} | '
            f'RS vs SPY {stock.get("rs_vs_spy", 0):+.1f}%  '
            f'Composite:{composite:.1f}\n'
        )

    send_telegram(
        f'🚨 <b>LONG-TERM SCAN — TOP {TOP_N}</b> 🚨\n'
        f'จากหุ้นที่ผ่าน Sentiment ทั้งหมด {total_passed} ตัว '
        f'(ผ่านทั้งกราฟ + งบการเงิน {len(fund_passed)} ตัว)\n'
        f'<i>Regime: {regime["label"]} | MIN_SCORE: {effective_min_score}</i>\n'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'{summary_rows}'
        f'━━━━━━━━━━━━━━━━━━━━━━━━\n'
        f'🏆 ≥9  🥇 ≥8  🥈 ≥7  🥉 ≥6  (Technical Score)'
    )
    time.sleep(2)

    for rank, (stock, headlines, confidence, composite, sent_bk, sent_label) in enumerate(top_results):
        ok = send_telegram(build_message(stock, headlines, confidence, rank + 1, sent_bk))
        log.info(
            f'ส่ง #{rank+1} {stock["ticker"]} '
            f'Tech:{stock["score"]} Sent:{sent_label}({confidence*100:.0f}%) Composite:{composite:.2f} '
            f'→ {"✅" if ok else "❌"}'
        )
        time.sleep(3)

    log.info(f'  เสร็จสิ้น! ส่ง Top {len(top_results)} จาก {total_passed} ตัว')


# ==============================================================================
