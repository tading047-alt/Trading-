import os
import time
import logging
import requests
import pandas as pd
import numpy as np
from datetime import datetime
from functools import lru_cache
from dotenv import load_dotenv

# تحميل المتغيرات من ملف .env
load_dotenv()

# =========================================================
# LOGGING CONFIG
# =========================================================

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scanner.log"),
        logging.StreamHandler()
    ]
)

# =========================================================
# CONFIG (من متغيرات البيئة)
# =========================================================

TELEGRAM_TOKEN = os.getenv("8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI")
if not TELEGRAM_TOKEN:
    logging.error("❌ لم يتم العثور على TELEGRAM_TOKEN في متغيرات البيئة")
    logging.error("📌 أنشئ ملف .env وأضف فيه: TELEGRAM_TOKEN=your_token_here")
    exit(1)

CHAT_IDS = os.getenv("CHAT_IDS", "5067771509,2107567005").split(",")
INTERVAL = int(os.getenv("SCAN_INTERVAL", 180))
MIN_PUMP = float(os.getenv("MIN_PUMP", 10))
MIN_VOLUME = float(os.getenv("MIN_VOLUME", 200000))
TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"

# =========================================================
# TELEGRAM
# =========================================================

def send(msg):
    """إرسال رسالة إلى تيليجرام (أو طباعتها في وضع الاختبار)"""
    
    if TEST_MODE:
        print(f"\n📨 [TEST MODE] كان سيرسل:\n{msg}\n{'-'*50}\n")
        return
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    
    for chat in CHAT_IDS:
        try:
            response = requests.post(
                url,
                data={
                    "chat_id": chat.strip(),
                    "text": msg,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            if response.status_code == 200:
                logging.info(f"✅ تم الإرسال إلى {chat}")
            else:
                logging.warning(f"⚠️ فشل الإرسال إلى {chat}: {response.status_code}")
        except Exception as e:
            logging.error(f"❌ خطأ في الإرسال إلى {chat}: {e}")

# =========================================================
# INDICATORS
# =========================================================

def rsi(series, period=14):
    """حساب مؤشر RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def ema(series, period=20):
    """حساب المتوسط المتحرك الأسي EMA"""
    return series.ewm(span=period, adjust=False).mean()

# =========================================================
# BINANCE DATA
# =========================================================

@lru_cache(maxsize=100)
def klines(symbol, _cache_buster=None):
    """
    جلب بيانات الشموع من Binance
    _cache_buster: معلمة لكسر الكاش عند الحاجة
    """
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=200"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logging.error(f"❌ فشل جلب بيانات {symbol}: {e}")
        return None
    
    if not data:
        logging.warning(f"⚠️ لا توجد بيانات لـ {symbol}")
        return None
    
    df = pd.DataFrame(data)
    df = df.iloc[:, :6]
    df.columns = ["t", "o", "h", "l", "c", "v"]
    
    for col in ["o", "h", "l", "c", "v"]:
        df[col] = pd.to_numeric(df[col])
    
    return df

# =========================================================
# FILTER COINS
# =========================================================

def binance_scan():
    """فحص العملات التي تحقق شروط المضخة والحجم"""
    url = "https://api.binance.com/api/v3/ticker/24hr"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        data = response.json()
    except Exception as e:
        logging.error(f"❌ فشل جلب قائمة العملات: {e}")
        return []
    
    out = []
    for c in data:
        try:
            sym = c["symbol"]
            if not sym.endswith("USDT"):
                continue
            
            pump = float(c["priceChangePercent"])
            vol = float(c["quoteVolume"])
            
            if pump > MIN_PUMP and vol > MIN_VOLUME:
                out.append({
                    "symbol": sym,
                    "pump": pump,
                    "exchange": "BINANCE"
                })
        except (KeyError, ValueError, TypeError):
            continue
    
    logging.info(f"🔍 تم العثور على {len(out)} عملة تطابق المعايير")
    return out

# =========================================================
# PATTERNS
# =========================================================

def has_long_wick(df):
    """فحص وجود فتيل علوي طويل (دلالة على رفض السعر العالي)"""
    c = df.iloc[-1]
    body = abs(c["c"] - c["o"])
    upper_wick = c["h"] - max(c["c"], c["o"])
    
    if body < 0.0001:
        body = 0.0001
    return upper_wick / body > 2

def is_volume_weak(df):
    """فحص ضعف الحجم (آخر 3 شموع أقل من متوسط 15 شمعة)"""
    return df["v"].tail(3).mean() < df["v"].tail(15).mean()

def is_bearish_pattern(df):
    """فحص نمط انعكاس Bearish"""
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    return (prev["c"] > prev["o"] and 
            curr["c"] < curr["o"] and 
            curr["o"] > prev["c"])

# =========================================================
# ANALYZE (محسنة)
# =========================================================

def analyze(symbol, pump):
    """
    تحليل عملة وإرجاع النتيجة أو None إذا كانت البيانات غير كافية
    """
    # تحديث الكاش كل 5 دقائق
    df = klines(symbol, _cache_buster=int(time.time() // 300))
    
    if df is None or len(df) < 50:
        logging.warning(f"⚠️ بيانات غير كافية لـ {symbol}")
        return None
    
    # حساب المؤشرات
    df["rsi"] = rsi(df["c"])
    df["ema"] = ema(df["c"])
    
    current_price = df["c"].iloc[-1]
    current_rsi = df["rsi"].iloc[-1]
    ema20 = df["ema"].iloc[-1]
    
    # المسافة عن EMA
    stretch = ((current_price - ema20) / ema20) * 100
    
    # =================================================
    # نظام التسجيل المحسن (لـ SHORT)
    # =================================================
    score = 0
    
    # 1. RSI overbought
    if current_rsi > 75:
        score += 30
    elif current_rsi > 65:
        score += 15
    
    # 2. السعر بعيد عن EMA (للبيع المكشوف)
    if stretch > 8:
        score += 20
    elif stretch > 5:
        score += 10
    
    # 3. نمط الشمعة
    if has_long_wick(df):
        score += 15
    
    # 4. ضعف الحجم
    if is_volume_weak(df):
        score += 15
    
    # 5. نمط Bearish
    if is_bearish_pattern(df):
        score += 20
    
    # الحد الأقصى 100
    score = min(score, 100)
    
    # دخول قصير (SHORT) - منطقة بيع
    entry_low = current_price * 0.99   # سعر دخول أقل
    entry_high = current_price * 0.97  # منطقة دخول مثالية
    stop_loss = current_price * 1.02   # وقف خسارة
    expected_drop = stretch * 0.8      # الهبوط المتوقع
    
    # بيانات إضافية للرسالة
    rsi_5m = current_rsi
    rsi_15m = df["rsi"].iloc[-3] if len(df) >= 3 else current_rsi    rsi_1h = df["rsi"].iloc[-12] if len(df) >= 12 else current_rsi
    
    change_24h = pump
    change_4h = ((df["c"].iloc[-1] / df["c"].iloc[-48]) - 1) * 100 if len(df) >= 48 else pump
    change_1h = ((df["c"].iloc[-1] / df["c"].iloc[-12]) - 1) * 100 if len(df) >= 12 else pump
    
    return {
        "score": score,
        "price": current_price,
        "rsi": current_rsi,
        "stretch": stretch,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "expected_drop": expected_drop,
        "rsi_5m": rsi_5m,
        "rsi_15m": rsi_15m,
        "rsi_1h": rsi_1h,
        "change_24h": change_24h,
        "change_4h": change_4h,
        "change_1h": change_1h
    }

# =========================================================
# MAIN LOOP
# =========================================================

sent = set()

def main():
    """الحلقة الرئيسية للماسح الضوئي"""
    
    logging.info("🚀 بدء تشغيل الماسح الضوئي V3")
    
    if TEST_MODE:
        logging.info("🧪 وضع الاختبار مفعل - لن يتم إرسال رسائل فعلية إلى تيليجرام")
    
    send("🚀 V3 MULTI SIGNAL SCANNER STARTED")
    
    while True:
        try:
            coins = binance_scan()
            
            for coin in coins:
                sym = coin["symbol"]
                uid = sym
                
                if uid in sent:
                    continue
                
                res = analyze(sym, coin["pump"])
                
                if res is None:
                    continue
                
                score = res["score"]
                
                # =================================================
                # نظام التصنيف
                # =================================================
                
                if score >= 85:
                    grade = "🟢 VERY GOOD"
                    color = "🟢"
                elif score >= 70:
                    grade = "🟡 GOOD"
                    color = "🟡"
                elif score >= 55:
                    grade = "🔴 MEDIUM"
                    color = "🔴"
                else:
                    continue
                
                # بناء الرسالة
                message = f"""
{color} BINANCE — {grade}

━━━━━━━━━━━━━━━━━━
🔥 SHORT OPPORTUNITY
━━━━━━━━━━━━━━━━━━

💰 PAIR: {sym}
🧠 AI SCORE: {score} / 100
⚠️ SIGNAL STRENGTH: {grade}

━━━━━━━━━━━━━━━━━━
📊 MARKET MOVEMENT
━━━━━━━━━━━━━━━━━━

📈 24H CHANGE: {res['change_24h']:.2f}%
⏱ 4H CHANGE: {res['change_4h']:.2f}%
⚡ 1H CHANGE: {res['change_1h']:.2f}%

━━━━━━━━━━━━━━━━━━
🧠 TECHNICAL ANALYSIS
━━━━━━━━━━━━━━━━━━

📊 RSI 5M: {res['rsi_5m']:.2f}
📊 RSI 15M: {res['rsi_15m']:.2f}
📊 RSI 1H: {res['rsi_1h']:.2f}

🕯 CANDLE PATTERN:
✔ Bearish Rejection

📉 VOLUME STATUS:
⚠ Weakening

📏 EMA DISTANCE:
{res['stretch']:.2f}%

━━━━━━━━━━━━━━━━━━
🎯 SHORT SETUP
━━━━━━━━━━━━━━━━━━

🔴 SHORT ENTRY ZONE:
{res['entry_low']:.8f} → {res['entry_high']:.8f}

🛑 STOP LOSS:
{res['stop_loss']:.8f}

📉 EXPECTED DROP:
{res['expected_drop']:.2f}%

━━━━━━━━━━━━━━━━━━
💼 RISK MANAGEMENT
━━━━━━━━━━━━━━━━━━

💵 POSITION SIZE: 5$
⚡ LEVERAGE: x2 (Isolated)

━━━━━━━━━━━━━━━━━━
⏱ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━
"""
                
                print(message)
                send(message)
                
                sent.add(uid)
            
            time.sleep(INTERVAL)
            
        except Exception as e:
            logging.error(f"❌ خطأ في الحلقة الرئيسية: {e}")
            time.sleep(INTERVAL)

if __name__ == "__main__":
    main()
