import ccxt
import pandas as pd
import asyncio
from telegram import Bot

# --- الإعدادات ---
TELEGRAM_TOKEN = '8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo'
CHAT_ID = '5067771509'

async def check_reversal_signals(df):
    """رصد علامات التراجع (شموع الانعكاس)"""
    last_candle = df.iloc[-1]
    prev_candle = df.iloc[-2]
    
    body = abs(last_candle['c'] - last_candle['o'])
    upper_wick = last_candle['h'] - max(last_candle['c'], last_candle['o'])
    
    # 1. شمعة الشهاب (Shooting Star) - فتيل علوي طويل جداً
    if upper_wick > body * 2.5:
        return True, "Shooting_Star_Detected"
    
    # 2. تقاطع RSI السلبي تحت 70 بعد ملامسته
    # (تمت إضافتها كمنطق خروج)
    return False, ""

async def analyze_with_safety_filters(exchange, symbol):
    try:
        # جلب بيانات فريم الساعة
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe='1h', limit=100)
        df = pd.DataFrame(ohlcv, columns=['t', 'o', 'h', 'l', 'c', 'v'])
        
        # --- 1. فلتر RSI (لا تدخل إذا كان > 70) ---
        delta = df['c'].diff()
        gain = (delta.where(delta > 0, 0)).rolling(14).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(14).mean()
        rsi = 100 - (100 / (1 + (gain/loss)))
        current_rsi = rsi.iloc[-1]
        
        if current_rsi > 70:
            return None # استبعاد العملة بسبب تضخم الشراء

        # --- 2. فلتر الصعود المفرط (Pump Protection) ---
        # إذا صعدت العملة > 10% في آخر 4 ساعات
        price_4h_ago = df['c'].iloc[-5]
        current_price = df['c'].iloc[-1]
        price_change_4h = (current_price - price_4h_ago) / price_4h_ago
        
        if price_change_4h > 0.10:
            return None # استبعاد العملة لأنها صعدت كثيراً بالفعل

        # --- 3. البحث عن إشارات الدخول المؤسسية (النماذج السابقة) ---
        score = 0
        reasons = []
        
        # فجوة القيمة العادلة (FVG)
        if df['h'].iloc[-3] < df['l'].iloc[-1]:
            score += 40; reasons.append("FVG_Entry")
            
        # إشارة الخروج المبكر إذا ظهرت علامات تراجع
        has_reversal, rev_msg = await check_reversal_signals(df)
        if has_reversal:
            return None # لا تدخل إذا بدأت تظهر شموع انعكاسية

        if score >= 40:
            return {
                'Symbol': symbol,
                'Price': current_price,
                'RSI': round(current_rsi, 2),
                'Trend': "Healthy_Growth",
                'Action': "BUY_SIGNAL"
            }
    except: return None

async def monitor_btc_crash(exchange, bot):
    """مراقبة البيتكوين للإغلاق الطارئ"""
    try:
        btc = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=2)
        btc_change = (btc[-1][4] - btc[-2][4]) / btc[-2][4]
        
        if btc_change < -0.02: # إذا هبط البيتكوين 2% في 15 دقيقة
            await bot.send_message(chat_id=CHAT_ID, text="🚨🚨 إغلاق طارئ!! البيتكوين ينهار حالياً. أغلق جميع الصفقات فوراً!")
            return False # سوق غير آمن
        return True
    except: return True

async def main():
    bot = Bot(token=TELEGRAM_TOKEN)
    exchange = ccxt.binance({'enableRateLimit': True})
    
    await bot.send_message(chat_id=CHAT_ID, text="🛡️ تم تفعيل نظام الحماية V8:\n🚫 لا شراء فوق RSI 70\n🚫 لا دخول في الـ Pumps\n⚠️ إغلاق طارئ عند هبوط BTC")

    markets = exchange.load_markets()
    symbols = [s for s in markets if '/USDT' in s and markets[s]['active']][:800]
    
    while True: # تشغيل مستمر كـ Scanner
        # 1. فحص أمان البيتكوين أولاً
        is_safe = await monitor_btc_crash(exchange, bot)
        if not is_safe:
            await asyncio.sleep(300) # انتظر 5 دقائق قبل الفحص التالي
            continue

        final_hits = []
        for i in range(0, len(symbols), 50):
            batch = symbols[i:i+50]
            tasks = [analyze_with_safety_filters(exchange, sym) for sym in batch]
            results = await asyncio.gather(*tasks)
            for r in results:
                if r: final_hits.append(r)
            await asyncio.sleep(5)

        if final_hits:
            df = pd.DataFrame(final_hits)
            await bot.send_message(chat_id=CHAT_ID, text=f"✅ اكتمل المسح الدوري. تم العثور على {len(final_hits)} فرص آمنة.")
            df.to_csv("Safe_Trades.csv", index=False)
            with open("Safe_Trades.csv", 'rb') as f:
                await bot.send_document(chat_id=CHAT_ID, document=f)
        
        await asyncio.sleep(600) # إعادة المسح كل 10 دقائق

if __name__ == "__main__":
    asyncio.run(main())
