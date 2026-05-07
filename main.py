import ccxt
import pandas as pd
import requests
import time

# --- إعدادات التلجرام الخاصة بك ---
TELEGRAM_TOKEN = '8603477836:AAGG6Outg3Z9vBI-NjWQ3ALJroh_Cye3l2c'
TELEGRAM_CHAT_ID = '6018153093'

def send_telegram_msg(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    payload = {'chat_id': TELEGRAM_CHAT_ID, 'text': message, 'parse_mode': 'Markdown'}
    try:
        requests.post(url, json=payload)
    except:
        print("خطأ في إرسال التلجرام")

# دالة حساب RSI يدوياً
def calculate_rsi(prices, period=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()
    rs = gain / loss
    return 100 - (100 / (1 + rs))

# إعداد المنصات
exchanges = {'Binance': ccxt.binance(), 'Gateio': ccxt.gateio()}

def get_market_data(ex_obj, symbol):
    try:
        bars = ex_obj.fetch_ohlcv(symbol, timeframe='5m', limit=50)
        df = pd.DataFrame(bars, columns=['time', 'open', 'high', 'low', 'close', 'vol'])
        rsi_series = calculate_rsi(df['close'])
        return rsi_series.iloc[-1]
    except:
        return None

def scan_market():
    for name, ex in exchanges.items():
        print(f"🔍 فحص منصة {name}...")
        try:
            tickers = ex.fetch_tickers()
            for symbol, ticker in tickers.items():
                if '/USDT' in symbol or ':USDT' in symbol:
                    change = ticker.get('percentage', 0)
                    # الشرط: ارتفاع +50%
                    if change >= 50:
                        rsi_val = get_market_data(ex, symbol)
                        # الشرط: RSI +80
                        if rsi_val and rsi_val >= 80:
                            last_price = ticker.get('last', 0)
                            msg = (
                                f"🚨 *فرصة شورت مؤكدة (بدون TA)*\n\n"
                                f"🏛 المنصة: `{name}`\n"
                                f"💰 العملة: `{symbol}`\n"
                                f"📈 الارتفاع: `{change:.2f}%`\n"
                                f"🔥 RSI (5m): `{rsi_val:.2f}`\n"
                                f"💵 السعر: `{last_price}`"
                            )
                            send_telegram_msg(msg)
                            time.sleep(1)
        except Exception as e:
            print(f"Error in {name}: {e}")

print("🚀 الرادار (النسخة الخفيفة) يعمل...")
while True:
    scan_market()
    time.sleep(180)
