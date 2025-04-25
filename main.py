import os
import base64
import datetime
import pickle
import asyncio
import pytz
import openai
import requests
from dateutil import parser
from dateparser.search import search_dates
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from googleapiclient.errors import HttpError

from telegram import Update, Bot
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters
)

# === Grundkonfiguration ===
if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl aus Umgebungsvariable erzeugt.")
    else:
        print("⚠️ Keine TOKEN_PKL_BASE64-Variable gefunden.")

BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", 8011259706))
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")

# === Kalenderfunktionen ===

def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

def list_all_calendars():
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)
    calendar_list = service.calendarList().list().execute()
    return [(cal['summary'], cal['id']) for cal in calendar_list.get('items', [])]

def get_events_for_date(target_date):
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)
    tz = pytz.timezone("Europe/Berlin")

    start = tz.localize(datetime.datetime(target_date.year, target_date.month, target_date.day, 0, 0)).isoformat()
    end = tz.localize(datetime.datetime(target_date.year, target_date.month, target_date.day, 23, 59, 59)).isoformat()

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

def add_event_to_calendar(summary, start_time, end_time, location=None):
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)
    event = {
        'summary': summary,
        'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Europe/Berlin'},
        'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Europe/Berlin'}
    }
    if location:
        event['location'] = location
    event = service.events().insert(calendarId='primary', body=event).execute()
    return f"✅ Termin hinzugefügt: {event.get('summary')}"

# === GPT-Briefings ===

def generate_chatgpt_briefing(summary):
    if not OPENAI_API_KEY:
        return None
    try:
        openai.api_key = OPENAI_API_KEY
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Fasse Termine in 2 Sätzen prägnant zusammen."},
                {"role": "user", "content": f"Erkläre folgenden Kalendereintrag: {summary}"}
            ],
            max_tokens=100,
            temperature=0.5
        )
        return response.choices[0].message["content"].strip()
    except Exception:
        return None

# === Todoist-Integration ===

def get_todoist_tasks():
    headers = {"Authorization": f"Bearer {TODOIST_API_TOKEN}"}
    params = {"filter": "today | overdue"}
    response = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers, params=params)
    if response.status_code != 200:
        return []
    return response.json()

# === Telegram Handlers ===

async def frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    results = search_dates(text, languages=['de'])
    if not results:
        await update.message.reply_text("❌ Kein Datum erkannt.")
        return
    parsed_date = results[0][1]
    await send_events_for_date(update, parsed_date)

async def send_events_for_date(update: Update, date: datetime.datetime):
    events = get_events_for_date(date)
    if not events:
        await update.message.reply_text(f"Keine Termine am {date.strftime('%d.%m.%Y')}.")
        return

    response = f"\n\n📅 Termine am {date.strftime('%d.%m.%Y')}\n"
    for name, items in events:
        response += f"\n🗓️ {name}:\n"
        for item in items:
            start = item['start'].get('dateTime', item['start'].get('date'))
            try:
                start_dt = parser.parse(start)
                start_str = start_dt.strftime('%H:%M')
            except:
                start_str = "Ganztägig"
            title = item.get('summary', 'Ohne Titel')
            response += f"- {start_str}: {title}\n"
    await update.message.reply_text(response[:4000])

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hallo! Starte mit /tomorrow oder schreib einfach ein Datum.")

async def tomorrow(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = datetime.datetime.utcnow() + datetime.timedelta(days=1)
    await send_events_for_date(update, date)

# === Zugstatus ===

FERIENTAGE = [... hier folgen noch Schulferien Daten ...]

# Zugstatus Funktion etc. baue ich sofort danach ein (wenn du bestätigst).

# === Scheduler / Start ===

def main():
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, frage))
    app.run_polling()

if __name__ == "__main__":
    main()

