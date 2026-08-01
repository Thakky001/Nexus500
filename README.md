# 📖 คู่มือ Russell 1000 Long-Term Scanner Bot — ฉบับสมบูรณ์

> **ระบบสแกนหุ้น Russell 1000 อัตโนมัติ** เน้นการลงทุนระยะยาว / DCA สะสมหุ้น  
> แจ้งเตือนผ่าน Telegram • บันทึกประวัติลง Google Sheets • Web Dashboard  
> ใช้งานฟรี 100% บน Render.com + Hugging Face + cron-job.org

---

## ภาพรวมระบบ

```
SEC API → รายชื่อหุ้นอเมริกาทั้งหมด (ดึงเฉพาะ Top 5,000 ตัวแรก)
    ↓
yfinance → กราฟย้อนหลัง 1 ปี (ทีละ 50 ตัว)
    ↓
คัดกรอง 5 ชั้น + Scoring (0–10):
  ชั้น 1 — Trend      : price > EMA20 > EMA50 > EMA200 + ADX ≥ 20
  ชั้น 2 — Momentum   : RSI 40–70 + MACD Histogram > -0.5
  ชั้น 3 — Volume     : Avg Volume (20d) ≥ 2M
  ชั้น 4 — Structure  : ห่างจาก 52W High ≤ 20% + Momentum 5 วัน ≥ -5%
    ↓
เฉพาะหุ้นที่ Score ≥ 6/10 เท่านั้นผ่าน
    ↓
ด่าน Layer 0 — Fundamentals (บังคับ):
  ROE > 15% + D/E < 1.5x + Net Margin > 10%
    ↓
Yahoo Finance RSS → ข่าวล่าสุด 3 ข่าว
    ↓
FinBERT (HuggingFace) → วิเคราะห์ Sentiment
    ↓
เฉพาะ "Positive" → จัดอันดับ Composite Score (Tech + Sentiment)
    ↓
ส่ง Top 5 เข้า Telegram + บันทึกลง Google Sheets
```

---

## Environment Variables ที่ต้องตั้งค่า (5 ตัว)

| ตัวแปร                        | คำอธิบาย                                        | จำเป็น |
| ----------------------------- | ----------------------------------------------- | ------ |
| `TELEGRAM_BOT_TOKEN`          | Token จาก @BotFather                            | ✅     |
| `TELEGRAM_CHAT_ID`            | Chat ID ของ Channel (เช่น `-1001234567890`)     | ✅     |
| `HF_API_TOKEN`                | Hugging Face API Token                          | ✅     |
| `GOOGLE_SHEET_ID`             | ID ของ Google Sheet (จาก URL)                   | แนะนำ  |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | JSON ทั้งหมดของ Service Account (inline string) | แนะนำ  |

> ⚠️ สองตัวสุดท้ายไม่ใส่ก็ได้ ระบบจะยังทำงานได้ แต่จะไม่มีประวัติใน Google Sheets และ Web Dashboard จะว่างเปล่า

---

## Phase 1 — ตั้งค่า Telegram

### 1.1 สร้าง Bot

1. เปิด Telegram → ค้นหา **@BotFather** → กดเริ่มสนทนา
2. พิมพ์ `/newbot` แล้วกด Send
3. ตั้งชื่อที่แสดง (Display Name) เช่น `Russell 1000 Scanner`
4. ตั้ง username ต้องลงท้ายด้วย `bot` เช่น `my_r1000_bot`
5. BotFather จะส่ง **Bot Token** กลับมา — คัดลอกเก็บไว้

```
รูปแบบ Token: 1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ
```

### 1.2 สร้าง Channel

1. ใน Telegram กดไอคอนดินสอ (เขียนข้อความใหม่) → **New Channel**
2. ตั้งชื่อ เช่น `Russell 1000 Daily Scan`
3. เลือกประเภท **Private** (แนะนำ เพื่อความปลอดภัย)
4. ข้ามขั้นตอนเพิ่มสมาชิก → กด Done

### 1.3 เพิ่ม Bot เป็น Admin ใน Channel

1. เข้าไปใน Channel ที่เพิ่งสร้าง
2. กดชื่อ Channel ด้านบน → **Administrators** → **Add Administrator**
3. ค้นหา username ของ Bot ที่สร้างไว้ → เลือก → ให้สิทธิ์ **Post Messages** → กด Done

### 1.4 หา Chat ID ของ Channel

**วิธีที่ 1 (ง่ายที่สุด)**

1. ส่งข้อความอะไรก็ได้เข้า Channel ก่อน 1 ข้อความ
2. เปิดเบราว์เซอร์แล้วไปที่:

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

(แทน `<TOKEN>` ด้วย Token จริงของคุณ)

3. ดูในผลลัพธ์ JSON หาส่วนนี้:

```json
"chat": {
  "id": -1001234567890,
  "type": "channel"
}
```

4. คัดลอกตัวเลขทั้งหมด **รวมเครื่องหมาย `-`** ด้านหน้า

**วิธีที่ 2 (กรณีหา Chat ID ไม่เจอ)**

เพิ่ม Bot `@userinfobot` เข้า Channel ชั่วคราว → มันจะแสดง Chat ID โดยอัตโนมัติ → ลบออกได้เลยหลังจากนั้น

> ✅ Chat ID ของ Channel จะขึ้นต้นด้วย `-100` เสมอ

---

## Phase 2 — ขอ Hugging Face API Token

ระบบใช้โมเดล **FinBERT** วิเคราะห์ Sentiment ของข่าวหุ้น ซึ่งต้องใช้ API Token

1. ไปที่ [https://huggingface.co](https://huggingface.co) → **Sign Up** (ฟรี)
2. คลิกรูปโปรไฟล์มุมบนขวา → **Settings**
3. เมนูด้านซ้าย → **Access Tokens**
4. กด **New token**
   - Name: ตั้งชื่ออะไรก็ได้ เช่น `r1000-bot`
   - Role: เลือก **Read**
5. กด **Generate a token**
6. คัดลอก Token ที่ได้เก็บไว้ทันที (จะแสดงแค่ครั้งเดียว)

```
รูปแบบ Token: hf_xxxxxxxxxxxxxxxxxxxx
```

---

## Phase 3 — ตั้งค่า Google Sheets (สำหรับเก็บประวัติ)

> ถ้าไม่ต้องการเก็บประวัติ ข้ามไป Phase 4 ได้เลย

### 3.1 สร้าง Google Sheet

1. ไปที่ [https://sheets.google.com](https://sheets.google.com) → **+ Blank spreadsheet**
2. ตั้งชื่อ เช่น `Russell 1000 Scanner History`
3. ดู URL ของ Sheet — คัดลอกส่วนที่เป็น **Sheet ID**:

```
https://docs.google.com/spreadsheets/d/  [SHEET_ID_อยู่ตรงนี้]  /edit
```

ตัวอย่าง: `1BxiMVs0XRA5nFMdKvBdBZjgmUUqptlbs74OgVE2upms`

> ℹ️ ระบบจะสร้าง worksheet ชื่อ **ScanHistory** ขึ้นเองอัตโนมัติในครั้งแรกที่รัน ไม่ต้องสร้างเอง

### 3.2 สร้าง Service Account

1. ไปที่ [https://console.cloud.google.com](https://console.cloud.google.com)
2. สร้าง Project ใหม่ (กด **New Project** → ตั้งชื่อ → กด **Create**)
3. เปิดใช้งาน Google Sheets API:
   - ค้นหา "Google Sheets API" → กด **Enable**
   - ค้นหา "Google Drive API" → กด **Enable** ด้วย
4. สร้าง Service Account:
   - ไปที่ **IAM & Admin** → **Service Accounts** → **+ Create Service Account**
   - ตั้งชื่อ เช่น `r1000-scanner`
   - กด **Create and Continue** → **Done**
5. ดาวน์โหลด JSON Key:
   - คลิกที่ Service Account ที่เพิ่งสร้าง
   - แท็บ **Keys** → **Add Key** → **Create new key** → เลือก **JSON** → **Create**
   - ไฟล์ `.json` จะถูกดาวน์โหลดมา — **อย่าแชร์ไฟล์นี้กับใคร**

### 3.3 แชร์ Google Sheet ให้ Service Account

1. เปิดไฟล์ JSON ที่ดาวน์โหลดมา → หาค่า `client_email` เช่น:
   ```
   r1000-scanner@your-project.iam.gserviceaccount.com
   ```
2. กลับไปที่ Google Sheet → กดปุ่ม **Share** มุมบนขวา
3. ใส่ `client_email` ด้านบน → เลือกสิทธิ์เป็น **Editor** → กด **Send**

### 3.4 เตรียม JSON สำหรับ Environment Variable

เปิดไฟล์ JSON → **คัดลอกเนื้อหาทั้งหมด** (ทั้งไฟล์) เก็บไว้ จะนำไปใส่เป็น `GOOGLE_SERVICE_ACCOUNT_JSON` ใน Render

> ⚠️ JSON ต้องอยู่ในบรรทัดเดียว (Render จัดการให้อัตโนมัติเมื่อวางลงในช่อง Environment Variable)

---

## Phase 4 — อัปโหลดโค้ดขึ้น GitHub

### 4.1 สมัคร GitHub (ถ้ายังไม่มี)

ไปที่ [https://github.com](https://github.com) → **Sign up** (ฟรี)

### 4.2 สร้าง Repository ใหม่

1. กดปุ่ม **+** มุมบนขวา → **New repository**
2. ตั้งค่าดังนี้:
   - Repository name: `r1000-bot` (หรือชื่ออื่น)
   - Visibility: **Private** (แนะนำ เพื่อปกป้องโค้ด)
   - ไม่ต้องติ๊กอะไรเพิ่ม
3. กด **Create repository**

### 4.3 อัปโหลดไฟล์

ต้องการไฟล์และโฟลเดอร์ทั้งหมดนี้:

```
r1000-bot/
├── app.py
├── config.py
├── logger.py
├── requirements.txt
├── .gitignore
├── core/
│   ├── fundamental.py
│   ├── orchestrator.py
│   ├── sentiment.py
│   └── technical.py
├── services/
│   ├── sheets.py
│   └── telegram.py
└── templates/
    └── dashboard.html
```

**วิธีผ่านเว็บ GitHub (ไม่ต้องติดตั้งอะไร)**

1. ใน Repository ที่สร้าง → กด **Add file** → **Upload files**
2. ลากไฟล์ทั้งสองขึ้นไป หรือกด **choose your files** แล้วเลือก
3. เลื่อนลงไปข้างล่าง → กด **Commit changes**

**วิธีผ่าน Command Line (ถ้ามี Git ติดตั้งแล้ว)**

```bash
git init
git add app.py requirements.txt
git commit -m "initial commit"
git remote add origin https://github.com/YOUR_USERNAME/r1000-bot.git
git push -u origin main
```

---

## Phase 5 — Deploy บน Render.com

### 5.1 สมัครและเชื่อม GitHub

1. ไปที่ [https://render.com](https://render.com) → **Get Started for Free**
2. เลือก **Sign up with GitHub** (สะดวกที่สุด)
3. อนุญาต Render เข้าถึง GitHub Account

### 5.2 สร้าง Web Service

1. หลัง Login → กด **New +** → **Web Service**
2. เลือก **Build and deploy from a Git repository**
3. กด **Connect** ที่ Repository `r1000-bot`

### 5.3 ตั้งค่า Build

กรอกข้อมูลดังนี้ (ช่องอื่นที่ไม่ได้ระบุให้ปล่อยเป็นค่าเริ่มต้น):

| ฟิลด์             | ค่าที่ต้องใส่                     |
| ----------------- | --------------------------------- |
| **Name**          | `r1000-bot` (หรือชื่ออื่น)        |
| **Region**        | Singapore (ใกล้ไทยที่สุด)         |
| **Runtime**       | Python 3                          |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app`                |
| **Instance Type** | Free                              |

### 5.4 ใส่ Environment Variables

เลื่อนลงไปที่ส่วน **Environment Variables** → กด **Add Environment Variable** ทีละตัว:

| Key                           | Value                                           |
| ----------------------------- | ----------------------------------------------- |
| `TELEGRAM_BOT_TOKEN`          | Token จาก @BotFather                            |
| `TELEGRAM_CHAT_ID`            | Chat ID ของ Channel เช่น `-1001234567890`       |
| `HF_API_TOKEN`                | Token จาก Hugging Face                          |
| `GOOGLE_SHEET_ID`             | ID ของ Google Sheet (ถ้าตั้งค่าไว้)             |
| `GOOGLE_SERVICE_ACCOUNT_JSON` | JSON ทั้งหมดของ Service Account (ถ้าตั้งค่าไว้) |

> ⚠️ **สำคัญมาก:** อย่าใส่ค่าเหล่านี้ในไฟล์โค้ดโดยตรง ใส่ใน Environment Variables เท่านั้น

### 5.5 Deploy

1. เลื่อนลงข้างล่างสุด → กด **Create Web Service**
2. รอ Build เสร็จ (ประมาณ 3–7 นาที) — ดู Log ด้านขวาได้
3. เมื่อสถานะเป็น **Live 🟢** จะได้ URL มา เช่น:

```
https://r1000-bot.onrender.com
```

### 5.6 ทดสอบระบบ

**ทดสอบว่าเซิร์ฟเวอร์ทำงาน:**

เปิดเบราว์เซอร์ → ไปที่:

```
https://r1000-bot.onrender.com/health
```

ควรได้:

```json
{
  "status": "healthy",
  "google_sheets": "configured"
}
```

**ทดสอบสแกนจริง:**

ไปที่:

```
https://r1000-bot.onrender.com/trigger
```

ควรได้:

```json
{
  "status": "accepted",
  "message": "LONG-TERM SCANNER (1000 Stocks) เริ่มสแกนแล้ว 🔍",
  "filters": "Score>=6 | Fund+Trend+RSI"
}
```

จากนั้นรอประมาณ **30–60 นาที** (เนื่องจากสแกน 1000 ตัว + ตรวจงบการเงินรายตัว) แล้วตรวจดูใน Telegram Channel

**ดู Web Dashboard:**

ไปที่:

```
https://r1000-bot.onrender.com/
```

จะเห็น Dashboard แสดงประวัติการสแกนทั้งหมดจาก Google Sheets

---

## Phase 6 — ตั้งเวลาอัตโนมัติด้วย cron-job.org

### 6.1 สมัครและสร้าง Cronjob

1. ไปที่ [https://cron-job.org](https://cron-job.org) → **Sign up** (ฟรี)
2. Verify email → Login
3. กด **CREATE CRONJOB**

### 6.2 ตั้งค่า Cronjob

| ฟิลด์        | ค่าที่ต้องใส่                            |
| ------------ | ---------------------------------------- |
| **Title**    | `Russell 1000 Bot Daily Trigger`         |
| **URL**      | `https://r1000-bot.onrender.com/trigger` |
| **Schedule** | Custom (ดูด้านล่าง)                      |

### 6.3 ตั้ง Schedule แบบ Custom

กดที่ **Custom** แล้วใส่ค่า:

```
นาที        : 0
ชั่วโมง      : 11
วันในเดือน   : *  (ทุกวัน)
เดือน        : *  (ทุกเดือน)
วันในสัปดาห์ : 1-5  (จันทร์–ศุกร์)
```

> 💡 เวลาไทย (ICT) = UTC+7 ดังนั้น **11:00 UTC = 18:00 เวลาไทย**

### 6.4 ตั้งค่า Advanced (สำหรับ Render Free Tier)

ใน cron-job.org → **Request settings**:

- Request Timeout: **300 seconds** (5 นาที เผื่อ Server cold start)
- Request Method: **GET**

4. กด **CREATE** — เสร็จสิ้น! 🎉

---

## API Endpoints

| Endpoint       | Method | ความหมาย                                        |
| -------------- | ------ | ----------------------------------------------- |
| `/`            | GET    | Web Dashboard แสดงประวัติการสแกน                |
| `/trigger`     | GET    | เริ่มสแกนหุ้น (เรียกโดย cron-job)               |
| `/health`      | GET    | ตรวจสอบสถานะระบบ + Google Sheets                |
| `/api/history` | GET    | ดึงประวัติการสแกนเป็น JSON (สูงสุด 300 ระเบียน) |

---

## ระบบ Scoring และเกณฑ์คัดกรอง

### Layer 0 — Fundamentals (บังคับ ตรวจหลัง Technical Score)

| เงื่อนไข                      | เกณฑ์      | หมายเหตุ                                                                |
| ----------------------------- | ---------- | ----------------------------------------------------------------------- |
| ROE (Return on Equity)        | > 15%      | ถ้าไม่ผ่านจะถูกตัดออกทันที                                              |
| D/E Ratio (หนี้ต่อทุน)        | < 1.5 เท่า | ข้ามเกณฑ์นี้สำหรับหุ้นกลุ่ม Financial Services (ค่า D/E มักสูงเป็นปกติ) |
| Net Profit Margin (กำไรสุทธิ) | > 10%      | ถ้าไม่ผ่านจะถูกตัดออกทันที                                              |

### Layer 1–4 — Technical Scoring (0–10 คะแนน)

| เงื่อนไข                                     | คะแนน       | หมายเหตุ                               |
| -------------------------------------------- | ----------- | -------------------------------------- |
| ผ่าน Trend (EMA Stack + EMA50 Slope)         | +2          | **บังคับ** ถ้าไม่ผ่านจะถูกตัดออกทันที  |
| ADX ≥ 20                                     | รวมใน Trend | **บังคับ**                             |
| ADX ≥ 30 (เทรนด์แข็ง)                        | +1 Bonus    |                                        |
| ผ่าน Momentum (RSI + MACD)                   | +2          | **บังคับ**                             |
| RSI อยู่ในโซน 40–55 (โซนเก็บของ)             | +1 Bonus    |                                        |
| ผ่าน Volume (Avg Vol ≥ 2M)                   | +2          | **บังคับ**                             |
| Vol วันนี้ ≥ 1.5x ค่าเฉลี่ย (แรงซื้อผิดปกติ) | +1 Bonus    |                                        |
| ราคาห่างจาก 52W High ≤ 20%                   | +1          |                                        |
| Momentum 5 วัน ≥ -5%                         | +1          |                                        |
| **คะแนนรวมสูงสุด**                           | **10**      | ต้องได้ ≥ 6 จึงผ่านไปตรวจ Fundamentals |

**เกณฑ์ Badge:**

| Badge     | คะแนน |
| --------- | ----- |
| 🏆 ELITE  | 9–10  |
| 🥇 STRONG | 8     |
| 🥈 GOOD   | 7     |
| 🥉 WATCH  | 6     |

---

## ตัวอย่างข้อความที่จะได้รับใน Telegram

**ข้อความสรุป (ส่งก่อน):**

```
🚨 LONG-TERM SCAN — TOP 5 🚨
จากหุ้น Positive ทั้งหมด 12 ตัว (ผ่านทั้งกราฟ + งบการเงิน 47 ตัว)
จัดอันดับจาก Technical Score + Sentiment Confidence
━━━━━━━━━━━━━━━━━━━━━━━━
🥇 $AAPL  Tech:9/10  Sentiment:94%
   RSI 52.3 | ADX 34.1 | ห่าง 52W -8.2%
🥈 $MSFT  Tech:8/10  Sentiment:91%
   RSI 48.7 | ADX 28.4 | ห่าง 52W -12.5%
...
━━━━━━━━━━━━━━━━━━━━━━━━
🏆 ≥9  🥇 ≥8  🥈 ≥7  🥉 ≥6  (Technical Score)
```

**ข้อความรายหุ้น (ส่งแยกแต่ละตัว):**

```
📈 $AAPL  🏆 ELITE  #1 TODAY'S TOP (Long-term)
██████████░ 9/10
━━━━━━━━━━━━━━━━━━━━━━━━
💲 ราคาปัจจุบัน  $189.50
📊 EMA 20/50/200  $184.20 / $178.30 / $162.40
━━━━━━━━━━━━━━━━━━━━━━━━
🏢 Fundamentals (ความแข็งแกร่ง)
  • ROE: 28.5%
  • Net Margin: 24.3%
  • D/E Ratio: 0.87x
  • Div Yield: 0.55%
━━━━━━━━━━━━━━━━━━━━━━━━
🔢 Technical Stats
  • RSI(14): 52.3 | MACD Hist: +0.1234
  • ห่าง 52W High: -8.2%
━━━━━━━━━━━━━━━━━━━━━━━━
🎯 แผนการสะสม (Accumulation Zones)

  ▶️ ไม้แรก (ราคาปัจจุบัน) : $189.50
  ▶️ รอรับย่อ (EMA50)       : $178.30
  ▶️ ไม้เผื่อ Panic (EMA200) : $162.40
━━━━━━━━━━━━━━━━━━━━━━━━
✨ Signals: ⚡ ADX มีเทรนด์แข็งแกร่ง  🏔 โครงสร้างราคายกตัว
━━━━━━━━━━━━━━━━━━━━━━━━
📰 ข่าว (🟢 Positive 94%)
  1. Apple reports record Q4 earnings
  2. iPhone 17 pre-orders surge past forecasts
  3. Apple Vision Pro gaining enterprise adoption
━━━━━━━━━━━━━━━━━━━━━━━━
⭐ Composite Score: 9.94  (Tech 9/10 + Sentiment 94%)
```

---

## ปรับแต่งเพิ่มเติม

แก้ค่าในส่วน Config ของ `app.py`:

```python
# ── Layer 0: Fundamentals ──────────────────────
MIN_ROE           = 0.15    # ROE > 15% (เพิ่มเป็น 0.20 ถ้าต้องการเข้มขึ้น)
MAX_DEBT_EQUITY   = 150.0   # D/E < 1.5 เท่า (ค่าในโค้ดเก็บเป็น % จาก yfinance)
MIN_PROFIT_MARGIN = 0.10    # Net Margin > 10% (เพิ่มเป็น 0.15 ถ้าต้องการกำไรสูง)

# ── ชั้น 1: Trend ──────────────────────────────
MIN_ADX         = 20    # เพิ่มเป็น 25 ถ้าต้องการเทรนด์แข็งขึ้น
EMA_SLOPE_DAYS  = 20    # จำนวนวันที่ใช้คำนวณ Slope ของ EMA50
MIN_EMA50_SLOPE = 0.0   # เพิ่มเป็น 0.5 ถ้าต้องการ Slope ขาขึ้นชัดเจน

# ── ชั้น 2: Momentum ───────────────────────────
RSI_LOW         = 40    # ลดเป็น 35 ถ้าต้องการ Oversold มากขึ้น
RSI_HIGH        = 70    # เพิ่มเป็น 75 ถ้ายอมรับ Overbought ได้
MIN_MACD_HIST   = -0.5  # เพิ่มเป็น 0.0 ถ้าต้องการ MACD Positive เท่านั้น

# ── ชั้น 3: Volume ─────────────────────────────
MIN_AVG_VOLUME  = 2_000_000  # เพิ่มเป็น 5_000_000 สำหรับหุ้น Liquid สูง

# ── ชั้น 4: Price Structure ────────────────────
MAX_PCT_FROM_52W = 20.0  # ลดเป็น 10 ถ้าต้องการหุ้นใกล้ All-time High
MIN_5D_MOMENTUM  = -5.0  # เพิ่มเป็น 0.0 ถ้าต้องการ Momentum บวกเท่านั้น

# ── Scoring ────────────────────────────────────
MIN_SCORE   = 6    # เพิ่มเป็น 7 ถ้าต้องการเกณฑ์เข้มข้นขึ้น
TOP_N       = 5    # จำนวนหุ้นสูงสุดที่ส่งเข้า Telegram

# ── Rate Limit ─────────────────────────────────
CHUNK_SIZE  = 50   # ลดเป็น 30 ถ้าโดน Rate Limit บ่อย
```

---

## แก้ไขปัญหาที่พบบ่อย

### ❓ เรียก `/trigger` แล้วได้ error เรื่อง missing variables

```json
{ "status": "error", "missing": ["TELEGRAM_BOT_TOKEN"] }
```

→ ตรวจสอบว่าใส่ Environment Variables ครบ 3 ตัวหลักบน Render แล้ว Redeploy

### ❓ `/health` แสดง `"google_sheets": "not configured"`

→ ปกติ ถ้าไม่ได้ตั้งค่า `GOOGLE_SHEET_ID` และ `GOOGLE_SERVICE_ACCOUNT_JSON`  
→ ถ้าตั้งค่าแล้วยังไม่ขึ้น ให้ตรวจสอบว่า JSON ถูกต้องและแชร์ Sheet ให้ Service Account แล้ว

### ❓ Bot ไม่ส่งข้อความเข้า Telegram

ตรวจสอบตามลำดับ:

1. ทดสอบ Token ที่เบราว์เซอร์: `https://api.telegram.org/bot<TOKEN>/getMe` — ถ้าเห็นข้อมูล Bot = Token ถูกต้อง
2. ตรวจสอบว่า Bot เป็น Admin ใน Channel และมีสิทธิ์ Post Messages
3. ตรวจสอบว่า Chat ID ขึ้นต้นด้วย `-100`

### ❓ Render หยุดทำงานเองหลังไม่มีคนใช้ 15 นาที

ปกติของ Free Tier — เซิร์ฟเวอร์จะ "นอนหลับ" เมื่อไม่มีคน Request เข้ามา  
cron-job.org จะ "ปลุก" ทุกวัน ซึ่งใช้เวลา cold start ~1–2 นาที → ระบบจะรอและทำงานต่อได้เองอัตโนมัติ

### ❓ FinBERT ตอบช้าหรือ Error

โมเดลบน Hugging Face Free Tier จะ cold start เมื่อไม่ได้ใช้งานนาน  
โค้ดมีระบบ Retry อัตโนมัติ 3 ครั้ง (รอ 60 วินาทีระหว่างครั้ง) อยู่แล้ว

### ❓ ไม่มีหุ้นผ่านเกณฑ์เลย หรือน้อยมาก

เป็นเรื่องปกติในตลาด Downtrend หรือช่วงที่ Sentiment ไม่ดี  
Bot จะส่งข้อความแจ้งว่า "ไม่มีหุ้นผ่านเกณฑ์" เข้า Telegram แทน มี 3 กรณี:

- ไม่ผ่านเกณฑ์ Technical เลย
- ผ่าน Technical แต่ไม่มีตัวไหนผ่านเกณฑ์งบการเงิน
- ผ่านทั้งคู่แต่ไม่มีข่าว Positive

### ❓ Google Sheets ไม่บันทึกข้อมูล

1. ตรวจสอบว่า Sheet ID ถูกต้อง (คัดลอกจาก URL ตรงๆ)
2. ตรวจสอบว่า Service Account Email ได้รับสิทธิ์ **Editor** ใน Sheet แล้ว
3. ดู Log บน Render ในส่วน "บันทึก Google Sheets" เพื่อดู Error message

### ❓ สแกนใช้เวลานานมาก

Russell 1000 มีหุ้น ~1000 ตัว โดยปกติระบบจะใช้เวลา 30–60 นาที เนื่องจาก:

- ดาวน์โหลดข้อมูลกราฟทีละ 50 ตัว + พัก 10 วินาทีระหว่าง chunk
- ตรวจงบการเงินทีละหุ้ย (พัก 0.5 วินาที/ตัว) เฉพาะตัวที่ผ่าน Technical
- ดึงข่าว + เรียก FinBERT API

---

## โครงสร้างโค้ด `app.py`

```
app.py
├── Config            — ค่า Environment Variables + เกณฑ์คัดกรองทุก Layer
├── Google Sheets     — get_gsheet(), save_to_sheet(), read_sheet_data()
├── Step 1            — get_1000_tickers() → โหลดรายชื่อ Russell 1000 จาก Wikipedia
│                       get_sp500_tickers() → Fallback กรณีโหลด Russell 1000 ไม่สำเร็จ
├── Step 2            — score_stock() + fetch_and_filter() → คัดกรอง 4 ชั้น Technical
├── Step 2.5          — check_fundamentals() → ตรวจ ROE / D/E / Net Margin
├── Step 3            — fetch_news() → Yahoo Finance RSS
├── Step 4            — analyze_sentiment() → FinBERT API
├── Step 5            — send_telegram() + build_message() → ส่งแจ้งเตือน
├── run_scan()        — งานหลักที่รันใน Background Thread
├── DASHBOARD_HTML    — HTML Web Dashboard (inline template)
└── Flask Routes
    ├── GET /          → Web Dashboard
    ├── GET /trigger   → เริ่มสแกน
    ├── GET /health    → ตรวจสอบสถานะ
    └── GET /api/history → JSON API
```

---

## ต้นทุน (ทั้งหมดฟรี)

| บริการ        | แผน                    | ค่าใช้จ่าย   |
| ------------- | ---------------------- | ------------ |
| GitHub        | Free                   | $0           |
| Render.com    | Free (750 ชม./เดือน)   | $0           |
| Hugging Face  | Free Inference API     | $0           |
| Google Sheets | Free (15 GB)           | $0           |
| Google Cloud  | Free (Service Account) | $0           |
| cron-job.org  | Free                   | $0           |
| Telegram      | Free                   | $0           |
| **รวม**       |                        | **$0/เดือน** |

---

> ⚠️ **Disclaimer:** ข้อมูลที่ระบบสร้างขึ้นเพื่อการศึกษาและทดลองเท่านั้น  
> ไม่ใช่คำแนะนำการลงทุน การลงทุนมีความเสี่ยง ผู้ลงทุนควรศึกษาข้อมูลเพิ่มเติมก่อนตัดสินใจเสมอ
