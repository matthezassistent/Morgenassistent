
import os
import base64
import pickle
import re
import datetime
import pytz
import requests
import asyncio
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, ContextTypes, filters
)
from dateutil import parser
from dateparser.search import search_dates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

from datetime import datetime, timedelta

print("🚀 Starte Bot...")

BOT_TOKEN = os.getenv("BOT_TOKEN")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "8011259706"))
pending_events = {}
pending_tasks = {}

if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl erzeugt")

def load_credentials():
    with open("token.pkl", "rb") as f:
        return pickle.load(f)

def find_time_and_date(text: str) -> datetime | None:
    tz = pytz.timezone("Europe/Berlin")
    match = re.search(r'\b(\d{1,2})[:h\.]?(\d{2})\b', text)
    if not match:
        return None
    hour, minute = int(match.group(1)), int(match.group(2))
    results = search_dates(text, languages=["de"])
    if not results:
        return None
    base_date = results[0][1].date()
    return tz.localize(datetime.combine(base_date, datetime.min.time()).replace(hour=hour, minute=minute))

def list_all_calendars():
    service = build("calendar", "v3", credentials=load_credentials())
    return [(c["summary"], c["id"]) for c in service.calendarList().list().execute().get("items", [])]

def get_events_for_date(date):
    tz = pytz.timezone("Europe/Berlin")
    service = build("calendar", "v3", credentials=load_credentials())
    start = date.replace(hour=0, minute=0).astimezone(pytz.utc).isoformat()
    end = date.replace(hour=23, minute=59).astimezone(pytz.utc).isoformat()
    events_all = []
    for name, cal_id in list_all_calendars():
        if "#weather" in cal_id or "holiday" in cal_id:
            continue
        try:
            events = service.events().list(calendarId=cal_id, timeMin=start, timeMax=end, singleEvents=True, orderBy="startTime").execute().get("items", [])
            if events:
                events_all.append((name, events))
        except Exception as e:
            print(f"Fehler bei {name}: {e}")
    return events_all

def get_todoist_tasks():
    try:
        headers = {"Authorization": f"Bearer {TODOIST_API_TOKEN}"}
        r = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers, params={"filter": "today | overdue"})
        if r.status_code != 200:
            return "❌ Fehler bei Todoist."
        tasks = r.json()
        if not tasks:
            return "✅ Keine Aufgaben."
        return "\n".join(f"- {t['content']} ({t.get('due', {}).get('string', '?')})" for t in tasks)
    except Exception as e:
        return f"❌ Fehler beim Abrufen: {e}"

def interpret_date_naturally(text: str) -> datetime | None:
    now = datetime.now(pytz.timezone("Europe/Berlin"))
    if "heute" in text.lower():
        return now
    elif "morgen" in text.lower():
        return now + timedelta(days=1)
    elif "übermorgen" in text.lower():
        return now + timedelta(days=2)
    result = search_dates(text, languages=["de"])
    return result[0][1] if result else None

def generate_event_summary(date):
    summary = []
    events = get_events_for_date(date)
    if not events:
        summary.append("📅 Keine Termine.")
    else:
        for name, es in events:
            block = f"🗓️ {name}:"
            for e in es:
                start_raw = e['start'].get('dateTime', e['start'].get('date'))
                dt = parser.parse(start_raw).astimezone(pytz.timezone("Europe/Berlin"))
                time_str = dt.strftime("%H:%M") if 'T' in start_raw else "Ganztägig"
                block += f"\n- {time_str}: {e.get('summary', 'Kein Titel')}"
            summary.append(block)
    todo = get_todoist_tasks()
    if todo:
        summary.append("📝 Aufgaben:\n" + todo)
    return summary

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hallo! Ich bin dein Assistent.")

async def termin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.replace("/termin", "").strip()
    dt = find_time_and_date(text)
    if not dt:
        await update.message.reply_text("❌ Keine Uhrzeit erkannt.")
        return
    parsed = {
        "title": text.split(" um ")[0].strip().title(),
        "start": dt,
        "end": dt + timedelta(hours=1),
        "location": None
    }
    pending_events[user_id] = parsed
    buttons = [[
        InlineKeyboardButton("✅ Ja", callback_data="confirm"),
        InlineKeyboardButton("❌ Nein", callback_data="cancel")
    ]]
    msg = f"📅 {parsed['title']} am {dt.strftime('%d.%m.%Y')} um {dt.strftime('%H:%M')}?"
    await update.message.reply_text(msg, reply_markup=InlineKeyboardMarkup(buttons))

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == "confirm" and user_id in pending_events:
        p = pending_events.pop(user_id)
        service = build("calendar", "v3", credentials=load_credentials())
        event = {
            "summary": p["title"],
            "start": {"dateTime": p["start"].isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": p["end"].isoformat(), "timeZone": "Europe/Berlin"},
        }
        service.events().insert(calendarId="primary", body=event).execute()
        await query.edit_message_text("✅ Termin eingetragen.")
    else:
        pending_events.pop(user_id, None)
        await query.edit_message_text("❌ Abgebrochen.")

async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(get_todoist_tasks())

async def frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    date = interpret_date_naturally(update.message.text)
    if not date:
        await update.message.reply_text("❌ Kein Datum erkannt.")
        return
    for chunk in generate_event_summary(date):
        await update.message.reply_text(chunk[:4000])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await frage(update, context)

async def send_morning(bot: Bot):
    date = datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin"))
    for chunk in generate_event_summary(date):
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])

async def send_evening(bot: Bot):
    date = datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin")) + timedelta(days=1)
    for chunk in generate_event_summary(date):
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])

async def post_init(app):
    await asyncio.sleep(1)
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    scheduler.add_job(send_morning, CronTrigger(hour=6, minute=40), args=[app.bot])
    scheduler.add_job(send_evening, CronTrigger(hour=19, minute=15), args=[app.bot])
    scheduler.start()
    print("✅ Scheduler gestartet.")

async def setup_application():
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    await app.bot.delete_webhook(drop_pending_updates=True)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("termin", termin))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(CommandHandler("frage", frage))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app

if __name__ == "__main__":
    import asyncio

    async def run():
        print("✅ Bot wird gestartet...")
        app = await setup_application()
        await app.initialize()
        await app.start()
        print("✅ Läuft.")
        await asyncio.Event().wait()

    try:
        asyncio.run(run())
    except RuntimeError as e:
        print("❌ Fehler beim Start:", e)
