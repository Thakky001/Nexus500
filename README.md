# 📖 คู่มือ S&P 500 Scanner Bot — ฉบับสมบูรณ์

> **ระบบสแกนหุ้น S&P 500 อัตโนมัติ** • แจ้งเตือนผ่าน Telegram ทุกวัน  
> ใช้งานฟรี 100% บน Render.com + Hugging Face + cron-job.org

---

## สิ่งที่ระบบทำ (ทุกวันจันทร์–ศุกร์ เวลา 18:00)

```
Wikipedia → รายชื่อหุ้น S&P 500 (~503 ตัว)
    ↓
yfinance → กราฟย้อนหลัง 1 ปี (ทีละ 50 ตัว)
    ↓
คัดกรอง: Volume > 1M │ ราคา > EMA50 > EMA200 │ RSI 45–65
    ↓
Yahoo Finance RSS → ข่าวล่าสุด 3 ข่าว
    ↓
FinBERT (HuggingFace) → วิเคราะห์ Sentiment
    ↓
Telegram Channel → แจ้งเตือนเฉพาะข่าว "Positive" 📬
```

---

## Phase 1 — ตั้งค่า Telegram

### 1.1 สร้าง Bot

1. เปิด Telegram ค้นหา **@BotFather**
2. พิมพ์ `/newbot`
3. ตั้งชื่อ Bot (ชื่อที่แสดง) เช่น `SP500 Scanner`
4. ตั้ง username (ลงท้าย `bot`) เช่น `my_sp500_bot`
5. คัดลอก **Bot Token** ที่ได้มาเก็บไว้ รูปแบบ: `1234567890:ABCdef...`

### 1.2 สร้าง Channel

1. กดปุ่ม **New Channel** ใน Telegram
2. ตั้งชื่อ Channel เช่น `SP500 Daily Scan`
3. เลือกประเภท **Private**
4. เข้า Channel Settings → **Restrict Saving Content** → เปิด ✅

### 1.3 เชื่อม Bot เข้า Channel

1. เข้า Channel → กด ชื่อ Channel ด้านบน → **Administrators**
2. กด **Add Administrator**
3. ค้นหาชื่อ Bot ที่สร้างไว้ → เพิ่มเป็น Admin
4. ให้สิทธิ์อย่างน้อย **Post Messages**

### 1.4 หา Chat ID

1. พิมพ์ข้อความอะไรก็ได้ใน Channel (อย่างน้อย 1 ข้อความ)
2. เปิดเบราว์เซอร์แล้วไปที่ URL นี้ (แทน `TOKEN` ด้วย Token จริง):

```
https://api.telegram.org/bot<TOKEN>/getUpdates
```

3. มองหาข้อความนี้ใน JSON:

```json
"chat": {
  "id": -1001234567890,   <-- นี่คือ Chat ID ของคุณ
  "type": "channel"
}
```

4. คัดลอกตัวเลขทั้งหมดรวมเครื่องหมาย `-` ไว้ด้วย

> **หมายเหตุ:** ถ้าไม่เห็น updates ให้ลองพิมพ์ข้อความใน Channel อีกครั้ง

---

## Phase 2 — เตรียมไฟล์โค้ด

ไฟล์ที่ต้องมี 2 ไฟล์:

```
sp500-bot/
├── app.py              ← โค้ดหลัก
└── requirements.txt    ← รายชื่อ Library
```

### ไฟล์ `requirements.txt`

```
flask>=3.0.0
yfinance>=0.2.40
pandas>=2.0.0
pandas-ta>=0.3.14b
requests>=2.31.0
lxml>=5.0.0
numpy>=1.26.0
gunicorn>=21.2.0
```

### ไฟล์ `app.py`

ใช้ไฟล์ `app.py` ที่แนบมาพร้อมคู่มือนี้ได้เลย

---

## Phase 3 — ขอ Hugging Face API Token

1. ไปที่ [https://huggingface.co](https://huggingface.co) → สมัครสมาชิก (ฟรี)
2. คลิกรูปโปรไฟล์ด้านบนขวา → **Settings**
3. เมนูซ้าย → **Access Tokens**
4. กด **New token** → ตั้งชื่อ → Role: **Read**
5. คัดลอก Token ที่ได้ไว้ รูปแบบ: `hf_xxxxxxxxxxxx`

---

## Phase 4 — ฝากโค้ดขึ้น GitHub

### 4.1 สมัคร GitHub (ถ้ายังไม่มี)

ไปที่ [https://github.com](https://github.com) → Sign up (ฟรี)

### 4.2 สร้าง Repository

1. กดปุ่ม **+** บน GitHub → **New repository**
2. ตั้งชื่อ: `sp500-bot`
3. เลือก **Private** (ปลอดภัยกว่า)
4. กด **Create repository**

### 4.3 อัปโหลดไฟล์

**วิธีที่ 1 — ผ่านเว็บ GitHub (ง่ายที่สุด)**

1. คลิก **Add file** → **Upload files**
2. ลากไฟล์ `app.py` และ `requirements.txt` ขึ้นไป
3. กด **Commit changes**

**วิธีที่ 2 — ผ่าน Command Line (ถ้ามี Git)**

```bash
git init
git add app.py requirements.txt
git commit -m "initial commit"
git remote add origin https://github.com/USERNAME/sp500-bot.git
git push -u origin main
```

---

## Phase 5 — Deploy บน Render.com

### 5.1 สมัครและสร้าง Web Service

1. ไปที่ [https://render.com](https://render.com) → Sign up ด้วย GitHub Account
2. กด **New +** → **Web Service**
3. เลือก **Connect a repository** → เชื่อมกับ GitHub
4. เลือก Repository `sp500-bot`

### 5.2 ตั้งค่า Build

| Field             | ค่าที่ต้องใส่                     |
| ----------------- | --------------------------------- |
| **Name**          | sp500-bot (หรือชื่ออื่น)          |
| **Runtime**       | Python 3                          |
| **Build Command** | `pip install -r requirements.txt` |
| **Start Command** | `gunicorn app:app`                |
| **Instance Type** | Free                              |

### 5.3 ใส่ Environment Variables

กด **Environment** → **Add Environment Variable** แล้วใส่ทีละตัว:

| Key                  | Value                                       |
| -------------------- | ------------------------------------------- |
| `TELEGRAM_BOT_TOKEN` | Token จาก @BotFather                        |
| `TELEGRAM_CHAT_ID`   | Chat ID ของ Channel (เช่น `-1001234567890`) |
| `HF_API_TOKEN`       | Token จาก Hugging Face                      |

> ⚠️ **สำคัญ:** อย่าใส่ค่าเหล่านี้ในโค้ดโดยตรง ใส่ใน Environment Variables เท่านั้น

### 5.4 Deploy

1. กด **Create Web Service**
2. รอ Deploy เสร็จ (ประมาณ 2–5 นาที)
3. เมื่อสถานะเป็น **Live** จะได้ URL มา เช่น:
   ```
   https://sp500-bot.onrender.com
   ```

### 5.5 ทดสอบ

เปิดเบราว์เซอร์ไปที่:

```
https://sp500-bot.onrender.com/trigger
```

ถ้าได้ response แบบนี้ = สำเร็จ ✅

```json
{
  "status": "accepted",
  "message": "เริ่มสแกนแล้ว! ผลจะส่งเข้า Telegram เมื่อเสร็จ"
}
```

รอประมาณ **20–40 นาที** แล้วตรวจดูใน Telegram Channel

---

## Phase 6 — ตั้งเวลาอัตโนมัติด้วย cron-job.org

1. ไปที่ [https://cron-job.org](https://cron-job.org) → สมัครฟรี
2. กด **CREATE CRONJOB**
3. ตั้งค่าดังนี้:

| Field        | ค่าที่ต้องใส่                            |
| ------------ | ---------------------------------------- |
| **Title**    | SP500 Bot Daily Trigger                  |
| **URL**      | `https://sp500-bot.onrender.com/trigger` |
| **Schedule** | Custom — ดูด้านล่าง                      |

4. ตั้ง Schedule แบบ Custom:

```
# ทำงานทุกวันจันทร์–ศุกร์ เวลา 11:00 UTC (= 18:00 เวลาไทย)
นาที: 0
ชั่วโมง: 11
วันในเดือน: *
เดือน: *
วันในสัปดาห์: 1-5
```

> 💡 **เวลาไทย (ICT) = UTC+7** ดังนั้น 18:00 ไทย = 11:00 UTC

5. กด **CREATE** — เสร็จสิ้น! 🎉

---

## API Endpoints

| Endpoint       | ความหมาย                          |
| -------------- | --------------------------------- |
| `GET /`        | ตรวจสอบว่า Bot ยังทำงานอยู่       |
| `GET /trigger` | เริ่มสแกนหุ้น (เรียกโดย cron-job) |
| `GET /health`  | Health check สำหรับ Render        |

---

## ตัวอย่างข้อความที่จะได้รับใน Telegram

```
🚨 S&P 500 Daily Scan 🚨
พบหุ้นน่าสนใจ 3 ตัว (จาก 47 ตัวที่ผ่านเกณฑ์กราฟ)
━━━━━━━━━━━━━━━━━━━━

📈 $AAPL  •  S&P 500 Scanner
━━━━━━━━━━━━━━━━━━━━
💲 ราคา:    $189.50
📊 EMA 50:  $182.30
📊 EMA 200: $171.20
🔢 RSI (14): 58.3
📦 Vol เฉลี่ย: 62.4M
━━━━━━━━━━━━━━━━━━━━
📰 ข่าวล่าสุด (Sentiment: 🟢 Positive)
  1. Apple reports record Q4 earnings beating expectations
  2. iPhone 17 pre-orders surge past analyst forecasts
  3. Apple Vision Pro gaining enterprise adoption
━━━━━━━━━━━━━━━━━━━━
⚠️ ข้อมูลนี้เพื่อการศึกษาเท่านั้น ไม่ใช่คำแนะนำการลงทุน
```

---

## แก้ไขปัญหาที่พบบ่อย

### ❓ เรียก `/trigger` แล้วได้ error เรื่อง Environment Variables

ตรวจสอบว่าใส่ค่าครบทุกตัวบน Render:

- `TELEGRAM_BOT_TOKEN`
- `TELEGRAM_CHAT_ID`
- `HF_API_TOKEN`

### ❓ Bot ไม่ส่งข้อความเข้า Telegram

1. ตรวจสอบว่า Bot เป็น Admin ใน Channel แล้ว
2. ตรวจสอบว่า Chat ID ขึ้นต้นด้วย `-100`
3. ลองทดสอบ Token โดยเปิดเบราว์เซอร์:
   ```
   https://api.telegram.org/bot<TOKEN>/getMe
   ```
   ถ้าได้ข้อมูล Bot กลับมา = Token ถูกต้อง

### ❓ Render หยุดทำงานเองหลังไม่ได้ใช้งาน 15 นาที (Free Tier)

ปกติของ Free Plan — cron-job.org จะ "ปลุก" เซิร์ฟเวอร์ทุกวัน ซึ่งใช้เวลาโหลดประมาณ 1–2 นาที แต่ระบบจะรอและทำงานต่อได้เอง

### ❓ FinBERT ตอบช้าหรือ Error ครั้งแรก

โมเดลบน Hugging Face Free Tier จะ "cold start" เมื่อไม่ได้ใช้งานนาน โค้ดมีระบบ Retry อัตโนมัติอยู่แล้ว (ลองใหม่ 3 ครั้ง)

### ❓ ไม่มีหุ้นผ่านเกณฑ์เลย

อาจเป็นเพราะตลาดอยู่ในช่วง Downtrend หรือ RSI สูง/ต่ำเกินไป ซึ่งเป็นเรื่องปกติ Bot จะส่งข้อความแจ้งว่า "ไม่มีหุ้นผ่านเกณฑ์"

---

## ปรับแต่งเพิ่มเติม (Optional)

แก้ค่าใน `app.py` บรรทัด Config:

```python
MIN_VOLUME    = 1_000_000   # เพิ่มเป็น 5_000_000 ถ้าต้องการหุ้น Liquid สูง
RSI_LOW       = 45          # ลดเป็น 40 ถ้าต้องการหุ้น Oversold มากขึ้น
RSI_HIGH      = 65          # เพิ่มเป็น 70 ถ้าต้องการรับหุ้น Momentum สูง
CHUNK_SIZE    = 50          # ลดเป็น 30 ถ้าโดน Rate Limit บ่อย
```

---

## ต้นทุน (ทุกอย่างฟรี)

| บริการ       | แผน                  | ค่าใช้จ่าย   |
| ------------ | -------------------- | ------------ |
| GitHub       | Free                 | $0           |
| Render.com   | Free (750 ชม./เดือน) | $0           |
| Hugging Face | Free Inference API   | $0           |
| cron-job.org | Free                 | $0           |
| Telegram     | Free                 | $0           |
| **รวม**      |                      | **$0/เดือน** |

---

> ⚠️ **Disclaimer:** ข้อมูลที่ระบบสร้างขึ้นเป็นเพื่อการศึกษาและทดลองเท่านั้น  
> ไม่ใช่คำแนะนำการลงทุน การลงทุนมีความเสี่ยง ผู้ลงทุนควรศึกษาข้อมูลเพิ่มเติมก่อนตัดสินใจ
