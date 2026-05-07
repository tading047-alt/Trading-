# quick_test.py
from telegram import Bot
import asyncio

TOKEN = "8628541851:AAGTo4LDtxv8WOy40L5YI7kqIdwv2SLNUKI"
CHAT_ID = "5067771509"

async def main():
    bot = Bot(token=TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="✅ البوت يعمل!")
    print("تم الإرسال")

asyncio.run(main())
