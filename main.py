import os
import telegram
from telegram.ext import Updater, CommandHandler
from datetime import datetime

# Bot-Token aus Umgebungsvariablen laden
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Telegram Bot Initialisierung
updater = Updater(token=BOT_TOKEN, use_context=True)
dispatcher = updater.dispatcher

# Kommando zum Starten
def start(update, context):
    context.bot.send_message(chat_id=update.effective_chat.id, text="Guten Morgen! Ich bin dein Assistent.")

# Kommando für tägliche Erinnerung
def today(update, context):
    now = datetime.now()
    date_string = now.strftime("%A, %d %B %Y")
    context.bot.send_message(chat_id=update.effective_chat.id, text=f"Heute ist {date_string}. Deine Termine und Aufgaben kommen gleich!")

# Hinzufügen der Handler
start_handler = CommandHandler('start', start)
today_handler = CommandHandler('today', today)

dispatcher.add_handler(start_handler)
dispatcher.add_handler(today_handler)

# Starten des Bots
updater.start_polling()
