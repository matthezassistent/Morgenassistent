import os
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes

# === ENV ===
BOT_TOKEN = os.getenv("BOT_TOKEN")

# === Feature-Schalter ===
USE_CALENDAR = True
USE_TODOIST = False
USE_GPT = False
USE_MAIL = False
USE_SUMMARY = False

# === Dummy-Handler-Importe (nur wenn aktiviert) ===
if USE_CALENDAR:
    from modules.calendar_handler import calendar_handlers  # placeholder
if USE_TODOIST:
    from modules.todoist_handler import todoist_handlers  # placeholder
if USE_GPT:
    from modules.gpt_handler import gpt_handlers  # placeholder
if USE_MAIL:
    from modules.mail_checker import mail_handlers  # placeholder
if USE_SUMMARY:
    from modules.summary_scheduler import init_scheduler  # placeholder

# === Basisbefehle ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hallo! Der Bot läuft modular.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

# === Main Setup ===
def main():
    app = Application.builder().token(BOT_TOKEN).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))

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
    app.run_polling()

if __name__ == "__main__":
    main()
