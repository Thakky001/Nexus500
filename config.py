import os

TELEGRAM_BOT_TOKEN          = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID            = os.environ.get("TELEGRAM_CHAT_ID", "")
HF_API_TOKEN                = os.environ.get("HF_API_TOKEN", "")
GOOGLE_SHEET_ID             = os.environ.get("GOOGLE_SHEET_ID", "")
GOOGLE_SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON", "")
PORTFOLIO_VALUE             = float(os.environ.get("PORTFOLIO_VALUE", "10000"))

HF_MODEL_URL = "https://router.huggingface.co/hf-inference/models/ProsusAI/finbert"

MIN_ROE           = 0.15
MAX_DEBT_EQUITY   = 150.0
MIN_PROFIT_MARGIN = 0.10
MAX_PE_RATIO      = 40.0
MAX_PEG_RATIO     = 2.5
MIN_ADX           = 20
EMA_SLOPE_DAYS    = 20
MIN_EMA50_SLOPE   = 0.0
RSI_LOW           = 40
RSI_HIGH          = 70
MIN_MACD_HIST     = -0.5
MIN_AVG_VOLUME    = 2_000_000
MIN_VOL_SURGE     = 0.0
MAX_PCT_FROM_52W  = 20.0
MIN_5D_MOMENTUM   = -5.0

FIB_LEVELS = [0.236, 0.382, 0.500]

STOP_LOSS_PCT       = 3.0
TRAIL_STOP_ATR_MULT = 2.0
TAKE_PROFIT_PCT     = 30.0
MAX_RISK_PER_TRADE  = 2.0
MAX_POSITION_PCT    = 25.0
MAX_PER_SECTOR      = 2

MIN_SCORE         = 6
TOP_N             = 5
CHUNK_SIZE        = 50
CHUNK_PAUSE       = 10
NEWS_PAUSE        = 5
AI_PAUSE          = 20
AI_RETRY_WAIT     = 60

# ── Market Regime ────────────────────────────────────────
REGIME_BULL_MIN_SCORE    = 6   # MIN_SCORE ปกติ
REGIME_CAUTION_MIN_SCORE = 7   # ตลาดระวัง → เกณฑ์เข้มขึ้น
REGIME_BEAR_MIN_SCORE    = 8   # ตลาดขาลง → เกณฑ์เข้มสุด

REGIME_BULL_RSI    = (35, 75)
REGIME_CAUTION_RSI = (38, 68)
REGIME_BEAR_RSI    = (30, 55)

# ── Sector Money Flow ────────────────────────────────────
SECTOR_FLOW_THRESHOLD = 5.0 # ถ้า <= -5% คือไหลออก, >= 5% คือไหลเข้า

# ── Timing Signal Thresholds ─────────────────────────────
TIMING_BUY_RSI_MAX       = 50   # RSI ≤ 50 → ไม่ Overbought
TIMING_BUY_PCT_EMA20_MAX = 2.0  # ราคาห่าง EMA20 ≤ 2% → ยังไม่ Extended
TIMING_EXT_RSI_MIN       = 65   # RSI ≥ 65 → Extended
TIMING_EXT_PCT_EMA20_MIN = 8.0  # ราคาห่าง EMA20 ≥ 8% → Extended

# ── Relative Strength ────────────────────────────────────
RS_PERIOD = 63  # ~3 เดือน

# ── Historical Consistency ───────────────────────────────
STREAK_LOOKBACK_DAYS = 30   # ดูย้อนหลัง 30 วัน
MAX_STREAK_BONUS     = 3    # Bonus สูงสุด 3 คะแนน

# ── Analyst Consensus ────────────────────────────────────
MIN_ANALYST_UPSIDE  = 15.0  # Upside % ที่ถือว่าน่าสนใจ
MIN_ANALYST_COUNT   = 10    # จำนวน Analyst ขั้นต่ำที่น่าเชื่อถือ

# ── Insider Activity ─────────────────────────────────────
INSIDER_LOOKBACK_DAYS = 90  # ดู Insider transaction ย้อนหลัง 90 วัน
