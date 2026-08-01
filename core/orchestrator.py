import time
from datetime import datetime, timezone
from config import *
from logger import log

from core.technical import get_all_us_tickers, fetch_and_filter
from core.fundamental import check_fundamentals
from core.sentiment import fetch_news, analyze_sentiment
from services.telegram import send_telegram, build_message
from services.sheets import save_to_sheet


def diversify_results(results: list, max_per_sector: int = MAX_PER_SECTOR) -> list:
    """
    กรองหุ้นไม่ให้กระจุกตัวใน Sector เดียวกันมากเกินไป
    results ต้องเรียงลำดับจากคะแนนมากไปน้อยแล้ว
    """
    final_list = []
    sector_counts = {}

    for item in results:
        stock = item[0]  # item = (stock_dict, headlines, confidence, composite, sent_bk)
        sector = stock.get("sector", "Unknown")

        if sector_counts.get(sector, 0) < max_per_sector:
            final_list.append(item)
            sector_counts[sector] = sector_counts.get(sector, 0) + 1

        if len(final_list) >= TOP_N:
            break

    return final_list

# ══════════════════════════════════════════════
#  งานหลัก — Background Thread
# ══════════════════════════════════════════════
def run_scan():
    """ฟังก์ชันหลักที่รันใน Background Thread"""
    log.info("══════════════════════════════════════════")
    log.info("  1000 STOCK LONG-TERM SCANNER เริ่มงาน")
    log.info(f"  Score>={MIN_SCORE} | ADX>{MIN_ADX} | RSI {RSI_LOW}-{RSI_HIGH}")
    log.info(f"  Vol>{MIN_AVG_VOLUME/1e6}M | MACD Hist>{MIN_MACD_HIST} | Full EMA Stack")
    log.info("══════════════════════════════════════════")

    # ขั้นตอนที่ 1: ดึงรายชื่อหุ้นทั้งหมด (สุ่มตัวอย่างประมาณ 7000+ ตัวจาก NASDAQ)
    scan_date = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    tickers = get_all_us_tickers()
    if not tickers:
        return

    candidates = fetch_and_filter(tickers)
    if not candidates:
        send_telegram(
            f"🔍 <b>Long-Term Scanner</b>\n\n"
            f"ไม่มีหุ้นผ่านเกณฑ์กราฟวันนี้ 📭\n"
            f"<i>(เกณฑ์: Score >= {MIN_SCORE}/10)</i>"
        )
        return

    # ── ด่านงบการเงิน ───────────────────────────────────────────────────
    fund_passed = []
    for stock in candidates:
        ticker = stock["ticker"]
        log.info(f"ตรวจงบการเงิน {ticker}...")
        passed, fund_details = check_fundamentals(ticker)
        if passed:
            stock.update(fund_details)
            fund_passed.append(stock)
        time.sleep(0.5)  # ป้องกันโดนแบน API

    if not fund_passed:
        send_telegram("ผ่านกราฟแต่ไม่มีหุ้นตัวไหนผ่านเกณฑ์งบการเงินวันนี้ 📭")
        return

    positive_results = []
    for stock in fund_passed:
        ticker = stock["ticker"]
        log.info(f"ดึงข่าว {ticker} (Score:{stock['score']})...")
        time.sleep(NEWS_PAUSE)

        headlines = fetch_news(ticker)
        if not headlines:
            log.info(f"  {ticker}: ไม่มีข่าว → ข้าม")
            continue

        log.info(f"  {ticker}: ส่ง FinBERT ({len(headlines)} ข่าว)...")
        time.sleep(AI_PAUSE)

        label, confidence, sent_bk = analyze_sentiment(headlines)
        log.info(f"  {ticker}: {label} ({confidence*100:.0f}%)")

        if label == "positive":
            val_score = stock.get("valuation_score", 0)
            composite = stock["score"] + val_score + confidence
            positive_results.append((stock, headlines, confidence, composite, sent_bk))

    if not positive_results:
        send_telegram(
            f"🔍 <b>Long-Term Scanner</b>\n\n"
            f"ผ่านเกณฑ์กราฟ + งบการเงิน {len(fund_passed)} ตัว\n"
            f"แต่ไม่มีข่าว Positive วันนี้ 📭"
        )
        return

    positive_results.sort(key=lambda x: x[3], reverse=True)
    top_results  = diversify_results(positive_results)
    total_passed = len(positive_results)

    # ── บันทึกลง Google Sheets ─────────────────────────────────────────────
    save_to_sheet(top_results, scan_date)

    # ── Summary Leaderboard ────────────────────────────────────────────────
    rank_medals  = ["🥇", "🥈", "🥉", "4️⃣", "5️⃣"]
    summary_rows = ""
    for rank, (stock, headlines, confidence, composite, sent_bk) in enumerate(top_results):
        medal    = rank_medals[rank] if rank < len(rank_medals) else f"{rank+1}."
        sent_pct = f"{confidence*100:.0f}%"
        summary_rows += (
            f"{medal} <b>${stock['ticker']}</b>  "
            f"Tech:{stock['score']}/10  Sentiment:{sent_pct}\n"
            f"    RSI {stock['rsi']} | ADX {stock['adx']} | "
            f"ห่าง 52W -{stock['pct_from_52w']:.1f}%\n"
        )

    send_telegram(
        f"🚨 <b>LONG-TERM SCAN — TOP {TOP_N}</b> 🚨\n"
        f"จากหุ้น Positive ทั้งหมด {total_passed} ตัว "
        f"(ผ่านทั้งกราฟ + งบการเงิน {len(fund_passed)} ตัว)\n"
        f"<i>จัดอันดับจาก Technical Score + Sentiment Confidence</i>\n"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"{summary_rows}"
        f"━━━━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 ≥9  🥇 ≥8  🥈 ≥7  🥉 ≥6  (Technical Score)"
    )
    time.sleep(2)

    for rank, (stock, headlines, confidence, composite, sent_bk) in enumerate(top_results):
        ok = send_telegram(build_message(stock, headlines, confidence, rank + 1, sent_bk))
        log.info(
            f"ส่ง #{rank+1} {stock['ticker']} "
            f"Tech:{stock['score']} Sent:{confidence*100:.0f}% Composite:{composite:.2f} "
            f"→ {'✅' if ok else '❌'}"
        )
        time.sleep(3)

    log.info(f"  เสร็จสิ้น! ส่ง Top {len(top_results)} จาก {total_passed} ตัว Positive")


# ══════════════════════════════════════════════
#  HTML Dashboard Template

