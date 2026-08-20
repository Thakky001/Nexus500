# 📖 คู่มือ Nexus500 Long-Term Scanner Bot — ฉบับสมบูรณ์ (อัปเดตล่าสุด)

> **ระบบสแกนหุ้นระดับมืออาชีพ** เน้นการลงทุนระยะยาว / DCA สะสมหุ้น  
> ผสานกราฟเทคนิค (Technical) + พื้นฐาน (Fundamental) + กระแสเงิน (Sector Flow) + พฤติกรรมผู้บริหาร (Insider) + อารมณ์ตลาด (AI Sentiment)
> แจ้งเตือนผ่าน Telegram • บันทึกประวัติลง Google Sheets • Web Dashboard  
> ใช้งานฟรี 100% บน Render.com + Hugging Face + cron-job.org

---

## 🚀 ฟีเจอร์เด่น (Nexus500)

ระบบถูกอัปเกรดให้มีความสามารถวิเคราะห์แบบ 360 องศา (Composite Score 0-25 คะแนน)

1. **Market Regime & Dynamic RSI**: ตรวจจับสภาวะตลาดจาก SPY อัตโนมัติ (Bull/Caution/Bear) และปรับเกณฑ์ RSI ให้เหมาะสม
2. **Timing Signal & Accumulation Zones**: แนะนำจุดเข้าซื้อ (BUY NOW, EXTENDED) พร้อมจุดรับตาม Fibonacci
3. **Relative Strength (RS vs SPY)**: ให้คะแนนพิเศษกับหุ้นที่ทำผลงานได้ดีกว่าตลาดรวม (S&P 500)
4. **Sector Money Flow**: ตรวจสอบกระแสเงินเข้า-ออก 11 กลุ่มอุตสาหกรรมในรอบ 1 เดือน หากกลุ่มไหนโดนเทขายหนัก หุ้นจะถูกหักคะแนน
5. **Insider Activity (90d)**: จับตาผู้บริหารซื้อ/ขาย หากขายหนักจะหักคะแนน หากซื้อจะเพิ่มคะแนน
6. **Earnings Calendar Filtering**: ป้องกันความเสี่ยง โดยปัดตกหุ้นที่มีประกาศงบภายใน 7 วัน ทันที
7. **Analyst Consensus & Quality Score**: ตรวจสอบคำแนะนำจากนักวิเคราะห์ และดูความสม่ำเสมอของ Cash Flow + รายได้
8. **AI Sentiment Enhancement**: ให้ AI (FinBERT) วิเคราะห์พาดหัวและเนื้อหาข่าว (Time-weighted) โดยให้ความสำคัญกับข่าวล่าสุดมากที่สุด
9. **Responsive Web Dashboard**: ตารางสรุปประวัติบนเว็บที่รองรับการแสดงผลบนโทรศัพท์มือถืออย่างสมบูรณ์แบบ

---

## ภาพรวมสถาปัตยกรรม (Architecture)

`
SEC API → รายชื่อหุ้นอเมริกาทั้งหมด (ดึง 5,000 ตัวแรก)
    ↓
yfinance → กราฟย้อนหลัง 1 ปี (ทีละ 50 ตัว)
    ↓
Step 1: Market Regime (core/market.py)
  - ดึง SPY เพื่อเช็คสภาวะตลาด กำหนด RSI Range และ Min Score อัตโนมัติ
    ↓
Step 2: Technical Screening (core/technical.py)
  - EMA Stack, MACD, Volume, RSI (Dynamic), RS vs SPY, Timing Signals
    ↓
Step 3: Fundamental & Earnings (core/fundamental.py)
  - ROE, D/E, Margin + Analyst Score + FCF/Rev Growth + Earnings Calendar (<= 7 days reject)
    ↓
Step 4: Context & Flow (core/insider.py, core/market_context.py)
  - ตรวจ Insider Trading (+1/-1) + Sector Money Flow (+1/-1) + Appearance Streak
    ↓
Step 5: AI Sentiment (core/sentiment.py)
  - Yahoo Finance RSS (Headline+Desc) → FinBERT (Time-weighted scoring)
    ↓
เฉพาะ "Positive" → รวมคะแนน Composite Score (Max 25)
    ↓
ส่ง Top N เข้า Telegram + บันทึกลง Google Sheets
`

---

## Environment Variables ที่ต้องตั้งค่า (5 ตัว)

| ตัวแปร                        | คำอธิบาย                                        | จำเป็น |
| ----------------------------- | ----------------------------------------------- | ------ |
| TELEGRAM_BOT_TOKEN          | Token จาก @BotFather                            | ✅     |
| TELEGRAM_CHAT_ID            | Chat ID ของ Channel (เช่น -1001234567890)     | ✅     |
| HF_API_TOKEN                | Hugging Face API Token                          | ✅     |
| GOOGLE_SHEET_ID             | ID ของ Google Sheet (จาก URL)                   | แนะนำ  |
| GOOGLE_SERVICE_ACCOUNT_JSON | JSON ทั้งหมดของ Service Account (inline string) | แนะนำ  |

---

## Phase 1 — ตั้งค่า Telegram

### 1.1 สร้าง Bot
1. เปิด Telegram → ค้นหา **@BotFather** → พิมพ์ /newbot
2. ตั้งชื่อและ username ต้องลงท้ายด้วย ot
3. คัดลอก **Bot Token** (1234567890:ABCdefGHIjklMNOpqrSTUvwxYZ)

### 1.2 สร้าง Channel
1. สร้าง **New Channel** (Private แนะนำ)
2. เพิ่ม Bot ที่สร้างไว้เป็น **Administrator** (ให้สิทธิ์ Post Messages)

### 1.3 หา Chat ID ของ Channel
ส่งข้อความเข้า Channel แล้วเปิด https://api.telegram.org/bot<TOKEN>/getUpdates หา "chat": {"id": -1001234567890} (Chat ID ต้องขึ้นต้นด้วย -100)

---

## Phase 2 — ขอ Hugging Face API Token
1. สมัคร [https://huggingface.co](https://huggingface.co)
2. ไปที่ **Settings** → **Access Tokens** → **New token** (Role: Read)
3. คัดลอก Token hf_xxxxxxxxxxxxxxxxxxxx

---

## Phase 3 — ตั้งค่า Google Sheets
1. สร้าง **Google Sheet** เปล่า คัดลอก **Sheet ID** จาก URL
2. สร้าง **Service Account** ใน Google Cloud Console พร้อมโหลด **JSON Key**
3. แชร์ Sheet ให้ email ของ Service Account (เป็น **Editor**)
4. คัดลอกเนื้อหา JSON เพื่อนำไปใช้เป็น Environment Variable

---

## Phase 4 — Deploy บน Render.com

1. สมัคร [https://render.com](https://render.com)
2. สร้าง **Web Service** เลือกจาก GitHub Repository
3. ตั้งค่า:
   - **Runtime**: Python 3
   - **Build Command**: pip install -r requirements.txt
   - **Start Command**: gunicorn app:app
   - **Instance Type**: Free
4. เพิ่ม **Environment Variables** 5 ตัว (ห้ามใส่ในไฟล์ตรงๆ)
5. กด **Deploy** และรอรับ URL (เช่น https://nexus500-bot.onrender.com)

---

## Phase 5 — ตั้งเวลาอัตโนมัติด้วย cron-job.org
1. ไปที่ [https://cron-job.org](https://cron-job.org)
2. สร้าง Cronjob ชี้ไปที่ https://nexus500-bot.onrender.com/trigger
3. ตั้งเวลาแบบ Custom (เช่น 11:00 UTC = 18:00 เวลาไทย) จันทร์-ศุกร์
4. **Request settings**: Timeout 300 seconds

---

## API Endpoints

| Endpoint       | Method | ความหมาย                                        |
| -------------- | ------ | ----------------------------------------------- |
| /            | GET    | Web Dashboard แสดงประวัติการสแกน (Responsive)   |
| /trigger     | GET    | เริ่มสแกนหุ้น (เรียกโดย cron-job)               |
| /health      | GET    | ตรวจสอบสถานะระบบ + Google Sheets                |
| /api/history | GET    | ดึงประวัติการสแกนเป็น JSON (สูงสุด 300 ระเบียน) |

---

## ปรับแต่งระบบ (config.py)
คุณสามารถปรับแต่งพฤติกรรมบอทได้ที่ไฟล์ config.py ได้ทั้งหมด เช่น:
- เกณฑ์งบการเงิน (ROE, Profit Margin, Debt to Equity)
- เกณฑ์ความผันผวนและการตัดคะแนน (Sector Flow Threshold, RSI ranges)
- สัดส่วนความเสี่ยง (Position Sizing, Stop Loss)
- ความเร็วในการสแกนและการดึง API

---

> ⚠️ **Disclaimer:** ข้อมูลและสัญญาณที่ระบบสร้างขึ้นจัดทำขึ้นเพื่อการศึกษาเท่านั้น  
> ไม่ใช่คำแนะนำการลงทุน การลงทุนมีความเสี่ยง ผู้ลงทุนควรศึกษาข้อมูลเพิ่มเติมก่อนตัดสินใจเสมอ
