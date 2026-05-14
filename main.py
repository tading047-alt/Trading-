#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
Binance Scanner Bot - ماسح عملات Binance مع إشارات بيع قصير (SHORT)
الإصدار: V3.0
"""

import os
import sys
import time
import json
import logging
import signal
from datetime import datetime
from functools import lru_cache
from typing import Optional, Dict, List, Any

import requests
import pandas as pd
import numpy as np
from dotenv import load_dotenv

# تحميل المتغيرات من ملف .env
load_dotenv()

# =========================================================
# إعدادات التسجيل (Logging)
# =========================================================

LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scanner.log", encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# =========================================================
# إعدادات التشغيل (من متغيرات البيئة)
# =========================================================

# إعدادات Telegram
TELEGRAM_TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TELEGRAM_TOKEN:
    logger.error("❌ لم يتم العثور على TELEGRAM_TOKEN في متغيرات البيئة")
    logger.error("📌 أنشئ ملف .env وأضف فيه: TELEGRAM_TOKEN=your_token_here")
    sys.exit(1)

CHAT_IDS = [x.strip() for x in os.getenv("CHAT_IDS", "").split(",") if x.strip()]
if not CHAT_IDS:
    logger.error("❌ لم يتم العثور على CHAT_IDS في متغيرات البيئة")
    sys.exit(1)

# إعدادات المسح
INTERVAL = int(os.getenv("SCAN_INTERVAL", "180"))
MIN_PUMP = float(os.getenv("MIN_PUMP", "10"))
MIN_VOLUME = float(os.getenv("MIN_VOLUME", "200000"))
TEST_MODE = os.getenv("TEST_MODE", "False").lower() == "true"

# عتبات التصنيف
SCORE_VERY_GOOD = int(os.getenv("SCORE_VERY_GOOD", "85"))
SCORE_GOOD = int(os.getenv("SCORE_GOOD", "70"))
SCORE_MEDIUM = int(os.getenv("SCORE_MEDIUM", "55"))

# إعدادات إدارة المخاطر
POSITION_SIZE = os.getenv("POSITION_SIZE", "5")
LEVERAGE = os.getenv("LEVERAGE", "2")

# =========================================================
# متغيرات عامة
# =========================================================

sent_signals = set()
running = True
cache_buster = int(time.time() // 300)


def signal_handler(sig, frame):
    """معالجة إشارة الإيقاف (Ctrl+C)"""
    global running
    logger.info("\n🛑 استلام إشارة إيقاف، جاري إغلاق الماسح...")
    running = False


signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)


# =========================================================
# دوال Telegram
# =========================================================

def send_telegram_message(msg: str) -> bool:
    """
    إرسال رسالة إلى تيليجرام
    تعيد True إذا نجح الإرسال إلى قناة واحدة على الأقل
    """
    if TEST_MODE:
        print(f"\n📨 [TEST MODE] كان سيرسل:\n{msg}\n{'-'*60}\n")
        return True
    
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    success = False
    
    for chat_id in CHAT_IDS:
        try:
            response = requests.post(
                url,
                json={
                    "chat_id": chat_id,
                    "text": msg,
                    "parse_mode": "HTML"
                },
                timeout=10
            )
            if response.status_code == 200:
                logger.info(f"✅ تم الإرسال إلى {chat_id}")
                success = True
            else:
                logger.warning(f"⚠️ فشل الإرسال إلى {chat_id}: {response.status_code}")
        except Exception as e:
            logger.error(f"❌ خطأ في الإرسال إلى {chat_id}: {e}")
    
    return success


def send_startup_message():
    """إرسال رسالة بدء التشغيل"""
    msg = f"""
🚀 <b>BINANCE SCANNER V3 STARTED</b>

📊 <b>الإعدادات:</b>
• الفاصل الزمني: {INTERVAL} ثانية
• أقل مضخة: {MIN_PUMP}%
• أقل حجم: {MIN_VOLUME:,.0f}$
• وضع الاختبار: {"نعم" if TEST_MODE else "لا"}

⏱ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""
    send_telegram_message(msg)


# =========================================================
# المؤشرات الفنية
# =========================================================

def calculate_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """حساب مؤشر RSI"""
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    return rsi


def calculate_ema(series: pd.Series, period: int = 20) -> pd.Series:
    """حساب المتوسط المتحرك الأسي EMA"""
    return series.ewm(span=period, adjust=False).mean()


def calculate_stochastic_rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """حساب Stochastic RSI"""
    rsi_values = calculate_rsi(series, period)
    min_rsi = rsi_values.rolling(period).min()
    max_rsi = rsi_values.rolling(period).max()
    
    stoch_rsi = (rsi_values - min_rsi) / (max_rsi - min_rsi) * 100
    return stoch_rsi.fillna(50)


# =========================================================
# أنماط الشموع
# =========================================================

def has_long_upper_wick(df: pd.DataFrame, ratio: float = 2.0) -> bool:
    """
    فحص وجود فتيل علوي طويل
    تشير إلى رفض السعر العالي (إشارة بيع)
    """
    candle = df.iloc[-1]
    body = abs(candle["c"] - candle["o"])
    upper_wick = candle["h"] - max(candle["c"], candle["o"])
    
    if body < 1e-8:
        body = 1e-8
    
    return upper_wick / body > ratio


def has_bearish_engulfing(df: pd.DataFrame) -> bool:
    """فحص نمط Bearish Engulfing"""
    if len(df) < 2:
        return False
    
    prev = df.iloc[-2]
    curr = df.iloc[-1]
    
    prev_bullish = prev["c"] > prev["o"]
    curr_bearish = curr["c"] < curr["o"]
    curr_engulfs = curr["o"] > prev["c"] and curr["c"] < prev["o"]
    
    return prev_bullish and curr_bearish and curr_engulfs


def is_volume_decreasing(df: pd.DataFrame, short: int = 3, long: int = 15) -> bool:
    """فحص ضعف الحجم (آخر 3 شموع أقل من متوسط 15 شمعة)"""
    if len(df) < long:
        return False
    return df["v"].tail(short).mean() < df["v"].tail(long).mean()


def is_rsi_divergence(df: pd.DataFrame) -> Dict[str, bool]:
    """فحص تباعد RSI (Divergence)"""
    if len(df) < 20:
        return {"bearish": False, "bullish": False}
    
    # أعلى 5 قمم للسعر و RSI
    price_highs = df["h"].tail(20)
    rsi_vals = df["rsi"].tail(20)
    
    # تباعد سلبي (Bearish Divergence): سعر أعلى ولكن RSI أقل
    price_peak_idx = price_highs.idxmax()
    rsi_at_peak = rsi_vals.loc[price_peak_idx]
    current_rsi = rsi_vals.iloc[-1]
    
    bearish_div = (price_highs.iloc[-1] > price_highs.iloc[-2] and 
                   current_rsi < rsi_at_peak)
    
    return {"bearish": bearish_div, "bullish": False}


# =========================================================
# جلب البيانات من Binance
# =========================================================

@lru_cache(maxsize=100)
def fetch_klines(symbol: str, _cache_key: int = None) -> Optional[pd.DataFrame]:
    """
    جلب بيانات الشموع من Binance
    _cache_key: معلمة لكسر الكاش عند الحاجة
    """
    url = f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=5m&limit=200"
    
    try:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        data = response.json()
    except requests.exceptions.RequestException as e:
        logger.error(f"❌ فشل جلب بيانات {symbol}: {e}")
        return None
    
    if not data:
        logger.warning(f"⚠️ لا توجد بيانات لـ {symbol}")
        return None
    
    df = pd.DataFrame(data)
    df = df.iloc[:, :6]
    df.columns = ["timestamp", "open", "high", "low", "close", "volume"]
    
    for col in ["open", "high", "low", "close", "volume"]:
        df[col] = pd.to_numeric(df[col])
    
    df["timestamp"] = pd.to_datetime(df["timestamp"], unit='ms')
    
    return df


def fetch_all_tickers() -> List[Dict[str, Any]]:
    """جلب قائمة جميع العملات من Binance"""
    url = "https://api.binance.com/api/v3/ticker/24hr"
    
    try:
        response = requests.get(url, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as e:
        logger.error(f"❌ فشل جلب قائمة العملات: {e}")
        return []


def scan_high_pump_coins() -> List[Dict[str, Any]]:
    """
    فحص العملات التي تحقق شروط المضخة العالية والحجم الكبير
    """
    data = fetch_all_tickers()
    if not data:
        return []
    
    candidates = []
    
    for item in data:
        try:
            symbol = item.get("symbol", "")
            if not symbol.endswith("USDT"):
                continue
            
            pump = float(item.get("priceChangePercent", 0))
            volume = float(item.get("quoteVolume", 0))
            
            if pump > MIN_PUMP and volume > MIN_VOLUME:
                candidates.append({
                    "symbol": symbol,
                    "pump": pump,
                    "volume": volume,
                    "last_price": float(item.get("lastPrice", 0)),
                    "high_24h": float(item.get("highPrice", 0)),
                    "low_24h": float(item.get("lowPrice", 0))
                })
        except (KeyError, ValueError, TypeError) as e:
            continue
    
    # ترتيب حسب نسبة المضخة (الأعلى أولاً)
    candidates.sort(key=lambda x: x["pump"], reverse=True)
    
    logger.info(f"🔍 تم العثور على {len(candidates)} عملة تطابق المعايير")
    
    return candidates


# =========================================================
# التحليل الأساسي للعملة
# =========================================================

def analyze_coin(symbol: str, pump: float) -> Optional[Dict[str, Any]]:
    """
    تحليل عملة بشكل عميق وإرجاع النتيجة
    """
    global cache_buster
    
    # تحديث الكاش كل 5 دقائق
    df = fetch_klines(symbol, _cache_key=cache_buster)
    
    if df is None or len(df) < 50:
        logger.debug(f"⚠️ بيانات غير كافية لـ {symbol} (الطول: {len(df) if df is not None else 0})")
        return None
    
    # حساب المؤشرات
    df["rsi"] = calculate_rsi(df["close"])
    df["ema20"] = calculate_ema(df["close"], 20)
    df["ema50"] = calculate_ema(df["close"], 50)
    df["stoch_rsi"] = calculate_stochastic_rsi(df["close"])
    
    current_price = df["close"].iloc[-1]
    current_rsi = df["rsi"].iloc[-1]
    current_stoch_rsi = df["stoch_rsi"].iloc[-1]
    ema20 = df["ema20"].iloc[-1]
    ema50 = df["ema50"].iloc[-1]
    
    # المسافة عن EMA
    stretch_from_ema20 = ((current_price - ema20) / ema20) * 100
    stretch_from_ema50 = ((current_price - ema50) / ema50) * 100
    
    # =================================================
    # نظام التسجيل للبيع القصير (SHORT)
    # =================================================
    score = 0
    signals = []
    
    # 1. RSI ذروة شراء (Overbought)
    if current_rsi > 80:
        score += 35
        signals.append(f"RSI ذروة شراء قوية ({current_rsi:.1f})")
    elif current_rsi > 70:
        score += 20
        signals.append(f"RSI ذروة شراء ({current_rsi:.1f})")
    elif current_rsi > 60:
        score += 10
    
    # 2. Stochastic RSI ذروة شراء
    if current_stoch_rsi > 80:
        score += 15
        signals.append(f"Stoch RSI ذروة شراء ({current_stoch_rsi:.1f})")
    
    # 3. السعر بعيد عن EMA20 (للبيع)
    if stretch_from_ema20 > 10:
        score += 25
        signals.append(f"سعر بعيد جداً عن EMA20 ({stretch_from_ema20:.1f}%)")
    elif stretch_from_ema20 > 5:
        score += 15
        signals.append(f"سعر بعيد عن EMA20 ({stretch_from_ema20:.1f}%)")
    elif stretch_from_ema20 > 3:
        score += 8
    
    # 4. نمط شمعة علوية طويلة
    if has_long_upper_wick(df):
        score += 20
        signals.append("نمط شمعة بفتيل علوي طويل")
    
    # 5. نمط Bearish Engulfing
    if has_bearish_engulfing(df):
        score += 25
        signals.append("نمط Bearish Engulfing")
    
    # 6. ضعف الحجم
    if is_volume_decreasing(df):
        score += 15
        signals.append("ضعف في حجم التداول")
    
    # 7. تباعد RSI سلبي
    divergence = is_rsi_divergence(df)
    if divergence["bearish"]:
        score += 20
        signals.append("تباعد RSI سلبي (Bearish Divergence)")
    
    # الحد الأقصى 100
    score = min(score, 100)
    
    # إذا كانت النتيجة أقل من العتبة، تخطي
    if score < SCORE_MEDIUM:
        return None
    
    # =================================================
    # إعدادات الدخول للصفقة (SHORT)
    # =================================================
    entry_low = current_price * 0.99    # منطقة دخول أولى
    entry_high = current_price * 0.97   # منطقة دخول مثالية
    stop_loss = current_price * 1.015   # وقف خسارة (1.5%)
    take_profit_1 = current_price * 0.96  # هدف أول (-4%)
    take_profit_2 = current_price * 0.94  # هدف ثاني (-6%)
    
    # الهبوط المتوقع بناءً على stretch
    expected_drop = min(stretch_from_ema20 * 0.7, 15)  # حد أقصى 15%
    
    # =================================================
    # بيانات إضافية للرسالة
    # =================================================
    # RSI على فترات مختلفة
    rsi_5m = current_rsi
    rsi_15m = df["rsi"].iloc[-3] if len(df) >= 3 else current_rsi
    rsi_1h = df["rsi"].iloc[-12] if len(df) >= 12 else current_rsi
    
    # التغيرات على فترات مختلفة
    change_24h = pump
    change_4h = ((df["close"].iloc[-1] / df["close"].iloc[-48]) - 1) * 100 if len(df) >= 48 else pump
    change_1h = ((df["close"].iloc[-1] / df["close"].iloc[-12]) - 1) * 100 if len(df) >= 12 else pump
    
    return {
        "score": score,
        "price": current_price,
        "rsi": current_rsi,
        "stretch": stretch_from_ema20,
        "entry_low": entry_low,
        "entry_high": entry_high,
        "stop_loss": stop_loss,
        "take_profit_1": take_profit_1,
        "take_profit_2": take_profit_2,
        "expected_drop": expected_drop,
        "rsi_5m": rsi_5m,
        "rsi_15m": rsi_15m,
        "rsi_1h": rsi_1h,
        "change_24h": change_24h,
        "change_4h": change_4h,
        "change_1h": change_1h,
        "signals": signals,
        "stoch_rsi": current_stoch_rsi
    }


# =========================================================
# بناء رسالة الإشارة
# =========================================================

def get_grade_and_color(score: int) -> tuple:
    """تحديد التصنيف واللون بناءً على النتيجة"""
    if score >= SCORE_VERY_GOOD:
        return "🟢 VERY GOOD", "🟢", "HIGH"
    elif score >= SCORE_GOOD:
        return "🟡 GOOD", "🟡", "MEDIUM"
    else:
        return "🔴 MEDIUM", "🔴", "LOW"


def build_signal_message(symbol: str, analysis: Dict[str, Any]) -> str:
    """بناء رسالة الإشارة المنسقة"""
    score = analysis["score"]
    grade, color, probability = get_grade_and_color(score)
    
    # قائمة الإشارات المستخدمة
    signals_list = "\n".join([f"  • {s}" for s in analysis["signals"][:5]])
    
    message = f"""
{color} <b>BINANCE — {grade}</b>

━━━━━━━━━━━━━━━━━━
🔥 <b>SHORT OPPORTUNITY</b>
━━━━━━━━━━━━━━━━━━

💰 <b>PAIR:</b> {symbol}
🧠 <b>AI SCORE:</b> {score} / 100
⚠️ <b>SIGNAL STRENGTH:</b> {grade}
📊 <b>PROBABILITY:</b> {probability}

━━━━━━━━━━━━━━━━━━
📈 <b>MARKET MOVEMENT</b>
━━━━━━━━━━━━━━━━━━

• 24H CHANGE: {analysis['change_24h']:.2f}%
• 4H CHANGE: {analysis['change_4h']:.2f}%
• 1H CHANGE: {analysis['change_1h']:.2f}%

━━━━━━━━━━━━━━━━━━
🧠 <b>TECHNICAL ANALYSIS</b>
━━━━━━━━━━━━━━━━━━

📊 RSI (5m): {analysis['rsi_5m']:.1f}
📊 RSI (15m): {analysis['rsi_15m']:.1f}
📊 RSI (1h): {analysis['rsi_1h']:.1f}
📊 Stoch RSI: {analysis.get('stoch_rsi', 0):.1f}

📏 EMA Distance: {analysis['stretch']:.2f}%

🔍 <b>Signals detected:</b>
{signals_list}

━━━━━━━━━━━━━━━━━━
🎯 <b>SHORT SETUP</b>
━━━━━━━━━━━━━━━━━━

🔴 <b>ENTRY ZONE:</b>
   {analysis['entry_high']:.8f} → {analysis['entry_low']:.8f}

🛑 <b>STOP LOSS:</b>
   {analysis['stop_loss']:.8f}

🎯 <b>TAKE PROFIT:</b>
   TP1: {analysis['take_profit_1']:.8f}
   TP2: {analysis['take_profit_2']:.8f}

📉 <b>EXPECTED DROP:</b>
   {analysis['expected_drop']:.2f}%

━━━━━━━━━━━━━━━━━━
💼 <b>RISK MANAGEMENT</b>
━━━━━━━━━━━━━━━━━━

💵 POSITION SIZE: ${POSITION_SIZE}
⚡ LEVERAGE: x{LEVERAGE} (Isolated)

━━━━━━━━━━━━━━━━━━
⏱ {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
━━━━━━━━━━━━━━━━━━
"""
    return message.strip()


# =========================================================
# الحلقة الرئيسية
# =========================================================

def save_signal_to_log(symbol: str, analysis: Dict[str, Any]):
    """حفظ الإشارة في ملف JSON للتتبع"""
    signal_data = {
        "timestamp": datetime.now().isoformat(),
        "symbol": symbol,
        "score": analysis["score"],
        "price": analysis["price"],
        "rsi": analysis["rsi"],
        "change_24h": analysis["change_24h"]
    }
    
    log_file = "signals_history.json"
    
    try:
        if os.path.exists(log_file):
            with open(log_file, 'r', encoding='utf-8') as f:
                history = json.load(f)
        else:
            history = []
        
        history.append(signal_data)
        
        # الاحتفاظ بآخر 1000 إشارة فقط
        if len(history) > 1000:
            history = history[-1000:]
        
        with open(log_file, 'w', encoding='utf-8') as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
            
    except Exception as e:
        logger.error(f"❌ فشل حفظ الإشارة في السجل: {e}")


def run_scanner():
    """تشغيل الماسح الضوئي"""
    global running, cache_buster
    sent = set()
    
    logger.info("🚀 بدء تشغيل الماسح الضوئي Binance V3")
    logger.info(f"⚙️ الإعدادات: الفاصل={INTERVAL}s | أقل مضخة={MIN_PUMP}% | أقل حجم={MIN_VOLUME:,.0f}$")
    
    if TEST_MODE:
        logger.info("🧪 وضع الاختبار مفعل - لن يتم إرسال رسائل فعلية إلى تيليجرام")
    
    # إرسال رسالة بدء التشغيل
    send_startup_message()
    
    last_cache_update = time.time()
    
    while running:
        loop_start = time.time()
        
        try:
            # تحديث الكاش كل 5 دقائق
            if time.time() - last_cache_update >= 300:
                cache_buster = int(time.time() // 300)
                last_cache_update = time.time()
                logger.debug("🔄 تحديث كاش البيانات")
            
            # فحص العملات
            candidates = scan_high_pump_coins()
            
            if not candidates:
                logger.info("⏳ لا توجد عملات تطابق المعايير، انتظار...")
                time.sleep(INTERVAL)
                continue
            
            signals_found = 0
            
            for coin in candidates:
                if not running:
                    break
                
                symbol = coin["symbol"]
                uid = symbol
                
                # تخطي الإشارات المكررة
                if uid in sent:
                    continue
                
                logger.info(f"📊 تحليل {symbol}...")
                
                analysis = analyze_coin(symbol, coin["pump"])
                
                if analysis is None:
                    continue
                
                signals_found += 1
                
                # بناء وإرسال الرسالة
                message = build_signal_message(symbol, analysis)
                print(f"\n{message}\n")
                send_telegram_message(message)
                
                # حفظ الإشارة في السجل
                save_signal_to_log(symbol, analysis)
                
                sent.add(uid)
                
                # تجنب إرسال إشارات كثيرة في دورة واحدة
                if signals_found >= 5:
                    logger.info("📊 تم الوصول للحد الأقصى للإشارات في هذه الدورة")
                    break
            
            if signals_found == 0:
                logger.info("⏳ لم يتم العثور على إشارات قوية في هذه الدورة")
            
            # حساب وقت الانتظار
            elapsed = time.time() - loop_start
            wait_time = max(1, INTERVAL - elapsed)
            logger.info(f"💤 انتظار {wait_time:.0f} ثانية حتى الدورة التالية...")
            
            # انتظار مع إمكانية الإيقاف
            for _ in range(int(wait_time)):
                if not running:
                    break
                time.sleep(1)
                
        except Exception as e:
            logger.error(f"❌ خطأ في الحلقة الرئيسية: {e}")
            import traceback
            logger.error(traceback.format_exc())
            time.sleep(INTERVAL)
    
    logger.info("👋 تم إيقاف الماسح الضوئي")


# =========================================================
# نقطة الدخول الرئيسية
# =========================================================

def main():
    """الدالة الرئيسية"""
    try:
        run_scanner()
    except KeyboardInterrupt:
        logger.info("\n👋 تم الإيقاف بواسطة المستخدم")
    except Exception as e:
        logger.error(f"❌ خطأ غير متوقع: {e}")
        import traceback
        logger.error(traceback.format_exc())
        sys.exit(1)


if __name__ == "__main__":
    main()
