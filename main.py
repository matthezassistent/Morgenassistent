import os
import base64
import pickle
import re
import datetime
import pytz
import requests
import asyncio
import nest_asyncio
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
from telegram.ext import (
    ApplicationBuilder,
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
import openai
from dateutil import parser
from dateparser.search import search_dates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# ENV-VARIABLEN
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = 8011259706
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
PORT = int(os.environ.get("PORT", 8443))

# TOKEN.PKL erzeugen (Render-kompatibel)
if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl aus Umgebungsvariable erzeugt.")

# Google Calendar
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
        if "#weather" in cal_id or "holiday" in cal_id:
            continue
        try:
            events = service.events().list(
                calendarId=cal_id,
                timeMin=start,
                timeMax=end,
                singleEvents=True,
                orderBy='startTime'
            ).execute().get('items', [])
            if events:
                events_all.append((name, events))
        except Exception as e:
            print(f"⚠️ Fehler bei Kalender '{name}' ({cal_id}): {e}")
    return events_all

# GPT Briefing
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
    except Exception as e:
        print(f"GPT-Fehler: {e}")
        return None

# Handlers (gekürzt)
# -> Du behältst alle deine bestehenden Handler-Funktionen:
#    - start, termin, todo, frage, button_handler, todo_button_handler, handle_text, usw.

# Datum interpretieren
def interpret_date_naturally(text: str) -> datetime.datetime | None:
    text = text.lower()
    now = datetime.datetime.now(pytz.timezone("Europe/Berlin"))
    if "heute" in text:
        return now
    elif "übermorgen" in text:
        return now + datetime.timedelta(days=2)
    elif "morgen" in text:
        return now + datetime.timedelta(days=1)
    result = search_dates(text, languages=["de"])
    return result[0][1] if result else None

# Tageszusammenfassung
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

# Zusammenfassungen senden
async def send_morning_summary(bot: Bot):
    print("⏰ Sende Morgenzusammenfassung…")
    today = datetime.datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin"))
    chunks = generate_event_summary(today)
    for chunk in chunks:
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])

async def send_evening_summary(bot: Bot):
    print("🌙 Sende Abendzusammenfassung…")
    tomorrow = datetime.datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin")) + datetime.timedelta(days=1)
    chunks = generate_event_summary(tomorrow)
    for chunk in chunks:
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])

# Post-Init
async def post_init(application):
    await asyncio.sleep(1)
    bot = application.bot
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    scheduler.add_job(send_morning_summary, 'cron', hour=6, minute=40, args=[bot])
    scheduler.add_job(send_evening_summary, 'cron', hour=21, minute=0, args=[bot])
    scheduler.start()
    print("✅ Scheduler gestartet.")

# Application Setup
async def setup_application() -> Application:
    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()
    await app.bot.delete_webhook(drop_pending_updates=True)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("termin", termin))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(CommandHandler("frage", frage))
    app.add_handler(CallbackQueryHandler(todo_button_handler, pattern="^(plan|verschiebe|done)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app

# Einstiegspunkt
if __name__ == '__main__':
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(setup_application())
    app.run_polling()
