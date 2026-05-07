import requests
import asyncio
from telegram import Bot
from datetime import datetime
import logging
import time

# ======================== الإعدادات ========================
TELEGRAM_BOT_TOKEN = "8716390236:AAEjPGJSYXN5FrqsuI845KhQoVzMfM_Suoo"
TELEGRAM_CHAT_ID = "5067771509"

# إعدادات التسجيل
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ======================== دوال API الخاصة بـ Gate.io ========================

def get_all_tickers():
    """
    جلب بيانات جميع العملات من Gate.io
    باستخدام API 2.0 (يقوم بإرجاع جميع العملات مرة واحدة)
    المصدر: توثيق API الرسمي لـ Gate.io
    """
    try:
        # استخدام API 2.0 لجلب جميع التيكرات مرة واحدة
        url = "https://data.gateapi.io/api2/1/tickers"
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            logger.info(f"✅ تم جلب بيانات {len(data)} عملة من Gate.io")
            return data
        else:
            logger.error(f"❌ فشل الجلب: {response.status_code}")
            return None
            
    except Exception as e:
        logger.error(f"❌ خطأ في الاتصال بـ Gate.io: {e}")
        return None

def get_all_tickers_v4():
    """
    طريقة بديلة باستخدام API v4
    المصدر: وثائق Gate.io API v4
    """
    try:
        url = "https://api.gateio.ws/api/v4/spot/tickers"
        response = requests.get(url, timeout=30)
        
        if response.status_code == 200:
            data = response.json()
            
            # تحويل البيانات إلى نفس تنسيق API 2.0 للتوحيد
            formatted_data = {}
            for ticker in data:
                currency_pair = ticker.get('currency_pair', '')
                # تحويل BTC_USDT إلى btc_usdt
                pair_key = currency_pair.lower().replace('_', '_')
                
                formatted_data[pair_key] = {
                    'last': ticker.get('last', 0),
                    'percentChange': float(ticker.get('change_percentage', 0)),
                    'high24hr': ticker.get('high_24h', 0),
                    'low24hr': ticker.get('low_24h', 0),
                    'baseVolume': ticker.get('base_volume', 0),
                    'quoteVolume': ticker.get('quote_volume', 0)
                }
            
            logger.info(f"✅ (v4) تم جلب بيانات {len(formatted_data)} عملة")
            return formatted_data
            
    except Exception as e:
        logger.error(f"❌ خطأ في API v4: {e}")
        return None

def filter_high_gainers(tickers_data, min_gain=100):
    """
    فلترة العملات التي حققت ارتفاع أكثر من min_gain%
    
    Args:
        tickers_data: قاموس بيانات العملات
        min_gain: الحد الأدنى لنسبة الارتفاع (افتراضي 100%)
    
    Returns:
        قائمة بالعملات التي تحقق الشرط
    """
    high_gainers = []
    
    if not tickers_data:
        return high_gainers
    
    for symbol, data in tickers_data.items():
        try:
            # استخراج نسبة التغير
            percent_change = float(data.get('percentChange', 0))
            
            # التحقق من أن العملة مرتفعة أكثر من min_gain%
            if percent_change > min_gain:
                high_gainers.append({
                    'symbol': symbol.upper(),
                    'percent_change': percent_change,
                    'last_price': data.get('last', 0),
                    'high_24h': data.get('high24hr', 0),
                    'low_24h': data.get('low24hr', 0),
                    'volume': data.get('baseVolume', 0)
                })
                
        except Exception as e:
            logger.warning(f"خطأ في معالجة {symbol}: {e}")
            continue
    
    # ترتيب حسب أعلى نسبة ارتفاع
    high_gainers.sort(key=lambda x: x['percent_change'], reverse=True)
    
    return high_gainers

def format_alert_message(gainers_list):
    """
    تنسيق رسالة التنبيه للإرسال إلى Telegram
    """
    if not gainers_list:
        return None
    
    current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    message = f"""
🚀 <b>تنبيه! عملات مرتفعة أكثر من 100% على Gate.io</b>
━━━━━━━━━━━━━━━━━━━━━━━━━━━
📅 الوقت: {current_time}
📊 عدد العملات: {len(gainers_list)}
━━━━━━━━━━━━━━━━━━━━━━━━━━━

"""
    
    for i, coin in enumerate(gainers_list[:15], 1):  # عرض أول 15 عملة فقط
        message += f"""
<b>{i}. {coin['symbol']}</b>
📈 الارتفاع: <b>+{coin['percent_change']:.2f}%</b>
💰 السعر الحالي: {coin['last_price']:.8f} USDT
📊 أعلى سعر 24h: {coin['high_24h']:.8f}
📉 أدنى سعر 24h: {coin['low_24h']:.8f}
"""
        
        if coin['volume']:
            message += f"💵 الحجم: {float(coin['volume']):.2f}\n"
        
        message += "─────────────────\n"
    
    message += f"\n✅ تم التحديث: {current_time}"
    
    return message

async def send_telegram_message(bot, message):
    """إرسال رسالة إلى Telegram"""
    try:
        if message:
            await bot.send_message(
                chat_id=TELEGRAM_CHAT_ID,
                text=message,
                parse_mode='HTML'
            )
            logger.info("✅ تم إرسال الرسالة إلى Telegram")
            return True
    except Exception as e:
        logger.error(f"❌ فشل إرسال رسالة Telegram: {e}")
        return False

async def main():
    """الدالة الرئيسية"""
    print("=" * 50)
    print("🚀 تشغيل بوت مراقبة عملات Gate.io")
    print("📊 البحث عن عملات ارتفعت أكثر من 100%")
    print("=" * 50)
    
    bot = Bot(token=TELEGRAM_BOT_TOKEN)
    
    # إرسال رسالة بدء التشغيل
    await send_telegram_message(
        bot,
        "🤖 <b>تم تشغيل بوت مراقبة Gate.io</b>\n"
        f"📅 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
        "🔍 جاري البحث عن عملات ارتفعت أكثر من 100%..."
    )
    
    while True:
        try:
            # جلب البيانات
            logger.info("🔄 جلب بيانات الأسواق من Gate.io...")
            
            # المحاولة باستخدام API 2.0
            tickers = get_all_tickers()
            
            # إذا فشل API 2.0، جرب API v4
            if not tickers:
                logger.info("محاولة استخدام API v4...")
                tickers = get_all_tickers_v4()
            
            if tickers:
                # فلترة العملات المرتفعة
                high_gainers = filter_high_gainers(tickers, min_gain=100)
                
                if high_gainers:
                    logger.info(f"🎯 تم العثور على {len(high_gainers)} عملة مرتفعة أكثر من 100%")
                    
                    # عرض في الطرفية
                    for coin in high_gainers[:10]:
                        logger.info(f"  📈 {coin['symbol']}: +{coin['percent_change']:.2f}%")
                    
                    # إرسال التنبيه إلى Telegram
                    message = format_alert_message(high_gainers)
                    await send_telegram_message(bot, message)
                else:
                    logger.info("ℹ️ لم يتم العثور على عملات مرتفعة أكثر من 100%")
            
            # انتظار 5 دقائق قبل التحديث التالي
            logger.info("⏰ انتظار 5 دقائق قبل التحديث التالي...")
            await asyncio.sleep(300)  # 5 دقائق
            
        except Exception as e:
            logger.error(f"❌ خطأ في الحلقة الرئيسية: {e}")
            await asyncio.sleep(60)  # انتظر دقيقة ثم حاول مجدداً

# ======================== التشغيل ========================
if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("⏹️ تم إيقاف البوت بواسطة المستخدم")
