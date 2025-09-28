import os
import requests
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import logging
import asyncio

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

DEEPSEEK_API_KEY = os.getenv("aimlapi_API_KEY", "04b21bbebead40c6a630f94125684d4a")
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_TOKEN", "8389962293:AAHrLNDdcvL9M1jvTuv4n2pUKwa8F2deBYY")

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text('مرحباً! 🎉 البوت يعمل الآن على Render!')

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_message = update.message.text
    await update.message.reply_text(f"📩 استقبلت رسالتك: {user_message}")

def main():
    print("🤖 بدء تشغيل البوت...")
    
    try:
        app = Application.builder().token(TELEGRAM_BOT_TOKEN).build()
        
        app.add_handler(CommandHandler("start", start_command))
        app.add_handler(MessageHandler(filters.TEXT, handle_message))
        
        print("✅ البوت يعمل! جرب /start في تليجرام")
        
        # التشغيل المستمر
        app.run_polling()
        
    except Exception as e:
        print(f"❌ خطأ: {e}")

if __name__ == '__main__':
    main()
