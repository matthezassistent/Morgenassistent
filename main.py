import os
import base64
import datetime
import pickle
import dateparser
import pytz
from dateutil import parser

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from telegram import Update
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# ✅ token.pkl erzeugen (falls nötig)
if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl aus Umgebungsvariable erzeugt.")
    else:
        print("⚠️ Keine TOKEN_PKL_BASE64-Variable gefunden.")

BOT_TOKEN = os.getenv("BOT_TOKEN")

# ✅ Zugang zum Kalender
def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

# ✅ Liste aller Kalender abrufen
def list_all_calendars():
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)
    calendar_list = service.calendarList().list().execute()
    calendars = calendar_list.get('items', [])
    return [(cal['summary'], cal['id']) for cal in calendars]

# ✅ Events für ein bestimmtes Datum (mit Pagination)
def get_events_for_date(target_date: datetime.datetime):
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)

    start = datetime.datetime(target_date.year, target_date.month, target_date.day, 0, 0, 0).isoformat() + 'Z'
    end = datetime.datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59).isoformat() + 'Z'

    all_events = []
    calendars = list_all_calendars()

    for name, cal_id in calendars:
        events = []
        page_token = None

        while True:
            events_result = service.events().list(
                calendarId=cal_id,
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy='startTime',
                pageToken=page_token
            ).execute()

            events.extend(events_result.get('items', []))
            page_token = events_result.get('nextPageToken')

            if not page_token:
                break

        if events:
            all_events.append((name, events))

    return all_events

# ✅ Telegram-Kommandos
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hallo! Ich bin dein Kalenderassistent.\nFrag mich z. B. 'Was ist morgen?'")

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = datetime.datetime.utcnow() + datetime.timedelta(days=1)
    await send_events_for_date(update, date)

# ✅ Verarbeitung natürlicher Sprache
async def frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    parsed_date = dateparser.parse(text, languages=['de'])

    if not parsed_date:
        await update.message.reply_text("❌ Ich konnte kein Datum erkennen.")
        return

    await send_events_for_date(update, parsed_date)

# ✅ Ausgabe generieren (mit europäischer Zeitzone)
async def send_events_for_date(update: Update, date: datetime.datetime):
    calendars_with_events = get_events_for_date(date)

    if not calendars_with_events:
        await update.message.reply_text(f"📅 Keine Termine am {date.strftime('%d.%m.%Y')}.")
        return

    response = f"📅 Termine am {date.strftime('%d.%m.%Y')}:\n\n"
    tz = pytz.timezone("Europe/Berlin")

    for name, events in calendars_with_events:
        response += f"🗓️ {name}:\n"
        for event in events:
            start_raw = event['start'].get('dateTime', event['start'].get('date'))
            try:
                dt_utc = parser.parse(start_raw)
                dt_local = dt_utc.astimezone(tz)
                start_time = dt_local.strftime("%H:%M")
            except Exception:
                start_time = "Ganztägig"

            summary = event.get('summary', 'Kein Titel')
            response += f"- {start_time}: {summary}\n"
        response += "\n"

    await update.message.reply_text(response)

# ✅ Bot starten
def main():
    print("👀 Bot gestartet und wartet auf Nachrichten.")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, frage))  # Freie Spracheingabe

    app.run_polling()

if __name__ == '__main__':
    main()
