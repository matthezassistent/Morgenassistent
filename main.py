import os
import asyncio
import base64
import pickle
import datetime
import pytz
import requests

from telegram import Update, Bot
from telegram.ext import (
    Application,
    CommandHandler,
    MessageHandler,
    ContextTypes,
    filters,
)
from googleapiclient.discovery import build
from dateparser.search import search_dates
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# === ENV ===
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "8011259706"))
TOKEN_PKL_BASE64 = os.getenv("TOKEN_PKL_BASE64")

# === token.pkl erzeugen, falls nötig ===
if not os.path.exists("token.pkl") and TOKEN_PKL_BASE64:
    with open("token.pkl", "wb") as f:
        f.write(base64.b64decode(TOKEN_PKL_BASE64))
    print("✅ token.pkl aus Umgebungsvariable erzeugt.")

# === Kalenderintegration ===
def get_calendar_events(start, end):
    with open("token.pkl", "rb") as token:
        creds = pickle.load(token)
    service = build("calendar", "v3", credentials=creds)

    events_output = []
    calendar_list = service.calendarList().list().execute()

    for cal in calendar_list.get("items", []):
        events_result = service.events().list(
            calendarId=cal["id"],
            timeMin=start.isoformat(),
            timeMax=end.isoformat(),
            singleEvents=True,
            orderBy="startTime"
        ).execute()

        events = events_result.get("items", [])
        for event in events:
            title = event.get("summary", "(kein Titel)")
            events_output.append({"summary": title})

    return events_output

async def kalender_heute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("✅ /kalender empfangen")

    tz = pytz.timezone("Europe/Berlin")
    now = datetime.datetime.now(tz)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + datetime.timedelta(days=1)

    try:
        events = get_calendar_events(start, end)
        if events:
            msg = "🗓️ Termine heute:\n" + "\n".join([f"- {e['summary']}" for e in events])
        else:
            msg = "Heute stehen keine Termine im Kalender."
    except Exception as e:
        msg = f"❌ Fehler beim Laden des Kalenders:\n{e}"

    await update.message.reply_text(msg)

async def global_frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_input = update.message.text
    tz = pytz.timezone("Europe/Berlin")
    parsed = search_dates(user_input, languages=["de"])

    if not parsed:
        return

    antworten = []
    for _, dt in parsed:
        dt = dt.astimezone(tz)
        start = dt.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)
        events = get_calendar_events(start, end)
        if events:
            antworten.append(
                f"🗓️ {start.strftime('%A, %d.%m.%Y')}:\n" +
                "\n".join([f"- {e['summary']}" for e in events])
            )
        else:
            antworten.append(f"Keine Termine am {start.strftime('%d.%m.%Y')}.")

    await update.message.reply_text("\n\n".join(antworten))

# === Tageszusammenfassungen ===
def init_scheduler(app):
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

    async def send_morning_summary():
        tz = pytz.timezone("Europe/Berlin")
        now = datetime.datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)
        events = get_calendar_events(start, end)
        if events:
            text = "Guten Morgen! Deine Termine heute:\n" + "\n".join([f"- {e['summary']}" for e in events])
        else:
            text = "Guten Morgen! Heute stehen keine Termine im Kalender."
        await app.bot.send_message(chat_id=CHAT_ID, text=text)

    async def send_evening_summary():
        tz = pytz.timezone("Europe/Berlin")
        now = datetime.datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)
        events = get_calendar_events(start, end)
        if events:
            text = "Guten Abend! Rückblick auf heute:\n" + "\n".join([f"- {e['summary']}" for e in events])
        else:
            text = "Guten Abend! Heute standen keine Termine im Kalender."
        await app.bot.send_message(chat_id=CHAT_ID, text=text)

    scheduler.add_job(send_morning_summary, trigger="cron", hour=7, minute=0)
    scheduler.add_job(send_evening_summary, trigger="cron", hour=21, minute=0)
    scheduler.start()

# === Basisbefehle ===
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("Hallo! Dein Assistent ist da.")

async def ping(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("peng")

# === Main Setup ===
async def setup_application():
    app = Application.builder().token(BOT_TOKEN).build()
    await app.bot.delete_webhook(drop_pending_updates=True)

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("ping", ping))
    app.add_handler(CommandHandler("kalender", kalender_heute))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_frage))

    init_scheduler(app)

    await app.initialize()
    await app.start()
    print("✅ Bot läuft auf Fly.io.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(setup_application())
