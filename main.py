# quick_test.py
from telegram import Bot
import asyncio

TOKEN = "8643715664:AAH-Th6cUZasbUrOJe6elCJuV_Fn6oTfd5g"
CHAT_ID = "5067771509"

async def main():
    bot = Bot(token=TOKEN)
    await bot.send_message(chat_id=CHAT_ID, text="✅ البوت يعمل!")
    print("تم الإرسال")

asyncio.run(main())
