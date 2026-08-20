import time
import requests
from config import *
from logger import log

# ══════════════════════════════════════════════
def fetch_news(ticker: str, max_items: int = 8) -> list:
    url = f"https://feeds.finance.yahoo.com/rss/2.0/headline?s={ticker}&region=US&lang=en-US"
    headlines = []
    try:
        resp = requests.get(url, timeout=10, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        from lxml import etree
        root  = etree.fromstring(resp.content)
        items = root.findall(".//item")
        for item in items[:max_items]:
            title = item.findtext("title", "").strip()
            desc  = item.findtext("description", "").strip()
            if title:
                full_text = f"{title}. {desc}" if desc else title
                headlines.append(full_text)
    except Exception as e:
        log.debug(f"ดึงข่าว {ticker} ล้มเหลว: {e}")
    return headlines


# ══════════════════════════════════════════════
#  STEP 4 — FinBERT Sentiment + Confidence
# ══════════════════════════════════════════════
def analyze_sentiment(headlines: list) -> tuple:
    if not headlines:
        return "neutral", 0.0, {"positive": 0, "negative": 0, "neutral": 0, "ratio": 0.0}

    headers = {"Authorization": f"Bearer {HF_API_TOKEN}"}
    results_per_headline = []
    
    for headline in headlines:
        payload = {"inputs": headline}
        for attempt in range(3):
            try:
                resp = requests.post(HF_MODEL_URL, headers=headers, json=payload, timeout=90)
                if resp.status_code == 429:
                    time.sleep(AI_RETRY_WAIT)
                    continue
                resp.raise_for_status()
                result = resp.json()
                if isinstance(result, list) and result:
                    inner = result[0]
                    if isinstance(inner, list):
                        best = max(inner, key=lambda x: x.get("score", 0))
                    else:
                        best = inner
                    results_per_headline.append({
                        "headline": headline,
                        "label":    best.get("label", "neutral").lower(),
                        "score":    best.get("score", 0.0),
                    })
                break
            except Exception:
                time.sleep(AI_RETRY_WAIT)
        time.sleep(1)  # Rate limit ระหว่างข่าว

    if not results_per_headline:
        return "neutral", 0.0, {"positive": 0, "negative": 0, "neutral": 0, "ratio": 0.0}
    
    label_counts = {"positive": 0, "negative": 0, "neutral": 0}
    total_conf   = {"positive": 0.0, "negative": 0.0, "neutral": 0.0}
    
    # น้ำหนักตามลำดับ: ข่าวล่าสุด = 1.0, ข่าวสุดท้าย = 0.5
    num_results = len(results_per_headline)
    weights = [1.0 - (i * 0.5 / max(num_results - 1, 1)) for i in range(num_results)]

    for idx, r in enumerate(results_per_headline):
        w = weights[idx]
        label_counts[r["label"]] += w
        total_conf[r["label"]]   += r["score"] * w
    
    majority_label = max(label_counts, key=label_counts.get)
    count_weight   = label_counts[majority_label]
    avg_confidence = total_conf[majority_label] / count_weight if count_weight > 0 else 0.0
    
    # ratio คิดแบบถ่วงน้ำหนัก
    total_weight = sum(weights)
    sentiment_ratio = label_counts["positive"] / total_weight if total_weight > 0 else 0.0
    
    breakdown = {
        "positive": round(label_counts["positive"], 1),
        "negative": round(label_counts["negative"], 1),
        "neutral": round(label_counts["neutral"], 1),
        "ratio": round(sentiment_ratio, 2)
    }
    
    return majority_label, avg_confidence, breakdown


# ══════════════════════════════════════════════
#  STEP 5 — สร้างข้อความ + ส่ง Telegram

