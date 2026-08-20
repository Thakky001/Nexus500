import yfinance as yf
import pandas_ta_classic as ta
from config import *
from logger import log

SECTOR_ETFS = {
    "Technology": "XLK",
    "Financial Services": "XLF",
    "Healthcare": "XLV",
    "Consumer Cyclical": "XLY",
    "Communication Services": "XLC",
    "Industrials": "XLI",
    "Consumer Defensive": "XLP",
    "Energy": "XLE",
    "Utilities": "XLU",
    "Real Estate": "XLRE",
    "Basic Materials": "XLB",
}

def get_sector_flows() -> dict:
    """
    ดาวน์โหลด Sector ETFs ครั้งเดียว
    คำนวณผลตอบแทน 1 เดือน (21 วันทำการ) ของแต่ละ ETF
    Return: { "Technology": 5.2, "Energy": -3.1, ... }
    """
    sector_flows = {}
    try:
        etf_list = list(SECTOR_ETFS.values())
        log.info("กำลังดาวน์โหลดข้อมูล Sector ETFs...")
        data = yf.download(etf_list, period="2mo", interval="1d", progress=False, group_by="ticker")
        
        for sector, etf in SECTOR_ETFS.items():
            try:
                if len(etf_list) == 1:
                    c = data["Close"]
                else:
                    c = data[etf]["Close"]
                c = c.dropna()
                if len(c) >= 21:
                    ret_1m = (float(c.iloc[-1]) - float(c.iloc[-21])) / float(c.iloc[-21]) * 100
                    sector_flows[sector] = round(ret_1m, 2)
                else:
                    sector_flows[sector] = 0.0
            except Exception as e:
                log.debug(f"ไม่สามารถคำนวณผลตอบแทนของ {etf}: {e}")
                sector_flows[sector] = 0.0
                
        log.info(f"คำนวณ Sector Flows สำเร็จ: {len(sector_flows)} sectors")
    except Exception as e:
        log.error(f"ดาวน์โหลด Sector ETFs ล้มเหลว: {e}")
        
    return sector_flows
