import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
from datetime import datetime

# Bot-Token aus Umgebungsvariablen laden
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Initialisiere den Bot mit der neuen API
application = Application.builder().token(BOT_TOKEN).build()

# Kommando zum Starten
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Guten Morgen! Ich bin dein Assistent.")

# Kommando für tägliche Erinnerung
async def today(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.now()
    date_string = now.strftime("%A, %d %B %Y")
    await update.message.reply_text(f"Heute ist {date_string}. Deine Termine und Aufgaben kommen gleich!")

# Hinzufügen der Handler
application.add_handler(CommandHandler("start", start))
application.add_handler(CommandHandler("today", today))

# Starten des Bots
application.run_polling()
