import os
import base64
from natural_question import natural_handlers
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
#
# === ENV ===
BOT_TOKEN = os.getenv("BOT_TOKEN")

# === Feature-Schalter ===
USE_CALENDAR = True  # temporär deaktivieren
USE_TODOIST = True
USE_GPT = True
USE_MAIL = False
USE_SUMMARY = True

# === Dummy-Handler-Importe (nur wenn aktiviert) ===
if USE_CALENDAR:
    from modules.calendar_handler import calendar_handlers
if USE_TODOIST:
    from modules.todoist_handler import todoist_handlers
if USE_GPT:
    from modules.gpt_handler import gpt_handlers
if USE_MAIL:
    from modules.mail_checker import mail_handlers
if USE_SUMMARY:
    from modules.summary_scheduler import init_scheduler

import base64

# === token.pkl erzeugen, falls nötig ===
if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl aus Umgebungsvariable erzeugt.")

# === Basisbefehle ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hallo! Der Bot läuft modular.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

# === Main Setup ===
import asyncio

async def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))

    for handler in natural_handlers:
        app.add_handler(handler)
    
    if USE_CALENDAR:
        print("✅ Kalender-Modul wird geladen...")
        for handler in calendar_handlers:
            app.add_handler(handler)

    if USE_TODOIST:
        print("✅ Todoist-Modul wird geladen...")
        for handler in todoist_handlers:
            app.add_handler(handler)

    if USE_GPT:
        print("✅ GPT-Modul wird geladen...")
        for handler in gpt_handlers:
            app.add_handler(handler)

    if USE_MAIL:
        print("✅ Mail-Modul wird geladen...")
        for handler in mail_handlers:
            app.add_handler(handler)

    if USE_SUMMARY:
        print("✅ Scheduler wird initialisiert...")
        init_scheduler(app)

    print("✅ Starte run_polling()...")
    await app.run_polling()  # <- await ist notwendig

if __name__ == "__main__":
    asyncio.run(main())
