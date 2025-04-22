import os
import base64
import datetime
import pickle
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from telegram import Update
from telegram.ext import ApplicationBuilder, CommandHandler, ContextTypes

# token.pkl aus Environment erzeugen
if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl aus Umgebungsvariable erzeugt.")
    else:
        print("⚠️ Keine TOKEN_PKL_BASE64-Variable gefunden.")

BOT_TOKEN = os.getenv("BOT_TOKEN")

# Kalender laden
def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

# Termine für morgen abrufen
def get_tomorrows_events():
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)

    now = datetime.datetime.utcnow()
    tomorrow = now + datetime.timedelta(days=1)
    start = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0).isoformat() + 'Z'
    end = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59).isoformat() + 'Z'

    events_result = service.events().list(
        calendarId='primary',
        timeMin=start,
        timeMax=end,
        singleEvents=True,
        orderBy='startTime'
    ).execute()

    events = events_result.get('items', [])
    if not events:
        return "Keine Termine für morgen. 🎉"

    output = "📅 Termine für morgen:\n\n"
    for event in events:
        start_time = event['start'].get('dateTime', event['start'].get('date'))
        summary = event.get('summary', 'Kein Titel')
        output += f"- {start_time}: {summary}\n"

    return output

# Telegram-Befehle
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hallo! Ich bin dein Kalenderassistent.")

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    reply = get_tomorrows_events()
    await update.message.reply_text(reply)

def main():
    print("👀 Bot gestartet und
