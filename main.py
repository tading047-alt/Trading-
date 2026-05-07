import time
import requests
from datetime import datetime

# =========================
# CONFIG
# =========================
TELEGRAM_BOT_TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"
TELEGRAM_CHAT_ID = "5067771509"

CHECK_INTERVAL = 300  # كل 5 دقائق
MIN_PUMP_PERCENT = 50  # العملات التي ارتفعت أكثر من 50%

# =========================
# TELEGRAM
# =========================
def send_telegram(message):
    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"

    data = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }

    try:
        requests.post(url, data=data, timeout=10)
    except Exception as e:
        print("Telegram Error:", e)

# =========================
# BINANCE
# =========================
def get_binance_gainers():
    url = "https://api.binance.com/api/v3/ticker/24hr"

    response = requests.get(url, timeout=20)
    data = response.json()

    gainers = []

    for coin in data:
        try:
            symbol = coin["symbol"]

            # فقط USDT
            if not symbol.endswith("USDT"):
                continue

            price_change = float(coin["priceChangePercent"])
            volume = float(coin["quoteVolume"])
            last_price = float(coin["lastPrice"])

            # فلترة العملات
            if (
                price_change >= MIN_PUMP_PERCENT
                and volume > 100000
                and last_price > 0
            ):
                gainers.append({
                    "symbol": symbol,
                    "change": price_change,
                    "price": last_price,
                    "volume": volume
                })

        except:
            pass

    gainers = sorted(gainers, key=lambda x: x["change"], reverse=True)

    return gainers

# =========================
# MAIN LOOP
# =========================
already_sent = set()

print("Bot Started...")

send_telegram("🚀 Binance Pump Bot Started")

while True:
    try:
        gainers = get_binance_gainers()

        if gainers:
            for coin in gainers:

                symbol = coin["symbol"]

                # منع التكرار
                if symbol in already_sent:
                    continue

                message = f"""
🚀 <b>PUMP DETECTED</b>

💰 Coin: <b>{symbol}</b>
📈 Change: <b>{coin['change']:.2f}%</b>
💵 Price: <b>{coin['price']}</b>
📊 Volume: <b>{coin['volume']:.0f}</b>

🕒 {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
"""

                print(message)

                send_telegram(message)

                already_sent.add(symbol)

        else:
            print("No pumps found")

    except Exception as e:
        print("ERROR:", e)

    time.sleep(CHECK_INTERVAL)
