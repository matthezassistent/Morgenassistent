import os
import base64
import datetime
import pickle
import dateparser
import pytz
import openai
import requests
import asyncio
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

from pyhafas import HafasClient
from pyhafas.profile import OebbProfile

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
CHAT_ID = 8011259706
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")

# Hafas Client (ÖBB)
hafas_client = HafasClient(OebbProfile())

# ✅ ChatGPT-Briefing generieren

def generate_chatgpt_briefing(summary):
    if not OPENAI_API_KEY:
        return None
    try:
        openai.api_key = OPENAI_API_KEY
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Du bist ein Assistent, der kurze Briefings zu Terminen schreibt."},
                {"role": "user", "content": f"Erstelle ein kurzes Briefing zu: '{summary}'"}
            ],
            max_tokens=100,
            temperature=0.7
        )
        return response.choices[0].message["content"].strip()
    except:
        return None

# ✅ Google Calendar Funktionen

def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

def list_all_calendars():
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)
    calendars = service.calendarList().list().execute().get('items', [])
    return [(cal['summary'], cal['id']) for cal in calendars]

def get_events_for_date(target_date):
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)
    start = target_date.replace(hour=0, minute=0, second=0).isoformat() + 'Z'
    end = target_date.replace(hour=23, minute=59, second=59).isoformat() + 'Z'

    events_all = []
    calendars = list_all_calendars()
    for name, cal_id in calendars:
        page_token = None
        events = []
        while True:
            result = service.events().list(
                calendarId=cal_id,
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy='startTime',
                pageToken=page_token
            ).execute()
            events.extend(result.get('items', []))
            page_token = result.get('nextPageToken')
            if not page_token:
                break
        if events:
            events_all.append((name, events))
    return events_all

# ✅ Todoist Aufgaben

def get_todoist_tasks():
    try:
        headers = {"Authorization": f"Bearer {TODOIST_API_TOKEN}"}
        params = {"filter": "today | overdue"}
        r = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers, params=params)
        if r.status_code != 200:
            return "❌ Fehler bei Todoist-Abruf."
        tasks = r.json()
        if not tasks:
            return "✅ Keine Aufgaben."
        return "\n".join(f"- {task['content']} ({task.get('due', {}).get('string', '?')})" for task in tasks)
    except:
        return "❌ Fehler beim Aufgabenlisten."

# ✅ Zusammenfassung erzeugen

def generate_event_summary(date):
    tz = pytz.timezone("Europe/Berlin")
    summary = []
    events = get_events_for_date(date)
    if not events:
        summary.append("📅 Keine Termine.")
    else:
        for name, es in events:
            block = f"🗓️ {name}:"
            for e in es:
                start_raw = e['start'].get('dateTime', e['start'].get('date'))
                start_dt = parser.parse(start_raw).astimezone(tz)
                start_time = start_dt.strftime("%H:%M") if 'T' in start_raw else "Ganztägig"
                block += f"\n- {start_time}: {e.get('summary', 'Kein Titel')}"
                briefing = generate_chatgpt_briefing(e.get('summary', ''))
                if briefing:
                    block += f"\n  💬 {briefing}"
            summary.append(block)
    todo = get_todoist_tasks()
    if todo:
        summary.append("📝 Aufgaben:\n" + todo)
    return summary

# ✅ Zugstatus Scotty (ÖBB)

async def get_next_train():
    now = datetime.datetime.now()
    connections = await hafas_client.connections("Hallein", "Salzburg Hbf", now)
    if connections:
        c = connections[0]
        dep = c.departure.strftime("%H:%M")
        arr = c.arrival.strftime("%H:%M")
        delay = c.departure_delay or 0
        status = "pünktlich" if delay == 0 else f"{delay} min verspätet"
        platform = c.origin.platform or "?"
        return f"🚆 {dep} Hallein → {arr} Salzburg Hbf, Gleis {platform}, {status}"
    return "🚆 Keine Verbindung gefunden."

async def get_fixed_train_status(fixed_time: str):
    today = datetime.datetime.now().date()
    fixed_dt = datetime.datetime.strptime(fixed_time, "%H:%M").replace(year=today.year, month=today.month, day=today.day)
    connections = await hafas_client.connections("Hallein", "Salzburg Hbf", fixed_dt)
    if connections:
        c = connections[0]
        dep = c.departure.strftime("%H:%M")
        delay = c.departure_delay or 0
        status = "pünktlich" if delay == 0 else f"{delay} min verspätet"
        platform = c.origin.platform or "?"
        return f"- {dep} Hallein: {status} (Gleis {platform})"
    return f"🚆 Keine Verbindung um {fixed_time} gefunden."

# ✅ Telegramm Kommandos

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hallo! Ich bin dein Assistent.")

async def frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    results = search_dates(text, languages=["de"])
    if not results:
        await update.message.reply_text("❌ Konnte kein Datum erkennen.")
        return
    date = results[0][1]
    chunks = generate_event_summary(date)
    for chunk in chunks:
        await update.message.reply_text(chunk[:4000])

async def zug(update: Update, context: ContextTypes.DEFAULT_TYPE):
    status = await get_next_train()
    await update.message.reply_text(status)

# ✅ Automatische Scheduler Aufgaben

async def send_daily_summary(bot: Bot):
    today = datetime.datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin"))
    chunks = generate_event_summary(today)
    for chunk in chunks:
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])

async def send_evening_summary(bot: Bot):
    tomorrow = datetime.datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin")) + datetime.timedelta(days=1)
    chunks = generate_event_summary(tomorrow)
    for chunk in chunks:
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])

async def send_morning_train_update(bot: Bot):
    status1 = await get_fixed_train_status("06:59")
    status2 = await get_fixed_train_status("07:04")
    message = "🚆 Zugstatus:\n\n" + status1 + "\n" + status2
    await bot.send_message(chat_id=CHAT_ID, text=message)

async def post_init(application):
    await asyncio.sleep(1)
    bot = application.bot
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    scheduler.add_job(send_daily_summary, 'cron', hour=6, minute=20, args=[bot])
    scheduler.add_job(send_evening_summary, 'cron', hour=21, minute=0, args=[bot])
    scheduler.add_job(send_morning_train_update, 'cron', hour=6, minute=30, args=[bot])
    scheduler.add_job(send_morning_train_update, 'cron', hour=6, minute=40, args=[bot])
    scheduler.start()
    print("🕒 Scheduler gestartet")

# ✅ Main

def main():
    print("👀 Bot gestartet.")
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("zug", zug))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, frage))
    app.run_polling()

if __name__ == '__main__':
    main()
