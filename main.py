import os
import base64

# Falls nötig: token.pkl aus der Umgebungsvariable rekonstruieren
if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl aus Umgebungsvariable erzeugt.")
    else:
        print("⚠️ Keine TOKEN_PKL_BASE64-Variable gefunden.")


import os
import datetime
import pickle
from telegram.ext import Updater, CommandHandler
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Telegram Bot Token aus Umgebungsvariable
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Kalender-TOKEN laden
def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

# Kalender-Abfrage für morgen
def get_tomorrows_events():
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)

    now = datetime.datetime.utcnow()
    tomorrow = now + datetime.timedelta(days=1)
    start = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0).isoformat() + 'Z'
    end = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59).isoformat() + 'Z'

    events_result =_
    def start(update, context):
    update.message.reply_text("👋 Hallo! Ich bin dein Kalenderassistent.")

def tomorrow(update, context):
    reply = get_tomorrows_events()
    update.message.reply_text(reply)

def main():
    print("👀 Bot gestartet und wartet auf Nachrichten.")
    
    updater = Updater(BOT_TOKEN, use_context=True)
    dp = updater.dispatcher

    dp.add_handler(CommandHandler("start", start))
    dp.add_handler(CommandHandler("tomorrow", tomorrow))

    updater.start_polling()  # Startet die Kommunikation mit Telegram
    updater.idle()           # Verhindert das Beenden des Programms

if __name__ == '__main__':
    main()

