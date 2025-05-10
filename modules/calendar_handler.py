from telegram.ext import CommandHandler, ContextTypes
from telegram import Update

async def kalender_test(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Kalendermodul ist geladen.")

calendar_handlers = [
    CommandHandler("kalendertest", kalender_test)
]
