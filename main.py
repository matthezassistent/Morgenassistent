import os
from telegram import Update
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "8011259706"))

# === Platzhalter: Handler-Module importieren (später aktivieren) ===
# from modules.calendar_handler import calendar_handlers
# from modules.todoist_handler import todoist_handlers
# from modules.gpt_handler import gpt_handlers
# from modules.mail_checker import mail_handlers
# from modules.summary_scheduler import init_scheduler

# === Basishandler ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hallo! Der Bot läuft.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("pong")

def main():
    application = Application.builder().token(BOT_TOKEN).build()

    # === Basis-Handler ===
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("ping", ping))

    # === Modul-Handler hinzufügen (später aktivieren) ===
    # for handler in calendar_handlers:
    #     application.add_handler(handler)

    # for handler in todoist_handlers:
    #     application.add_handler(handler)

    # for handler in gpt_handlers:
    #     application.add_handler(handler)

    # for handler in mail_handlers:
    #     application.add_handler(handler)

    # init_scheduler(application)  # z.B. für Morgen-/Abendzusammenfassung

    # === Start Polling ===
    application.run_polling()

if __name__ == "__main__":
    main()
