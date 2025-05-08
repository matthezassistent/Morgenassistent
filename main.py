import os
import base64
import pickle
import re
import datetime
import pytz
import requests
import asyncio
from openai import AsyncOpenAI

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
from dateutil import parser
from dateparser.search import search_dates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from email_bot_handlers import mail_command, mail_callback_handler
# from your_calendar_module import load_credentials  # Anpassen an deine Struktur
# from your_utils import interpret_date_naturally, generate_event_summary  # Anpassen an deine Struktur

pending_events = {}

# ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = 8011259706
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
PORT = int(os.environ.get("PORT", 8443))

application = ApplicationBuilder().token(BOT_TOKEN).build()
application.add_handler(CommandHandler("mail", mail_command))
application.add_handler(CallbackQueryHandler(mail_callback_handler, pattern="^(archive|defer):"))

if not os.path.exists("token.pkl"):
    encoded_token = os.getenv("TOKEN_PKL_BASE64")
    if encoded_token:
        with open("token.pkl", "wb") as f:
            f.write(base64.b64decode(encoded_token))
        print("✅ token.pkl aus Umgebungsvariable erzeugt.")

def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

import json

openai_client = AsyncOpenAI(api_key=OPENAI_API_KEY)  # <-- Async Client korrekt initialisiert

from datetime import datetime
import json

def find_time_and_date(text: str) -> datetime | None:
    tz = pytz.timezone("Europe/Berlin")

    # 1. Suche explizite Uhrzeit (18:30, 18h30, 18.30)
    time_match = re.search(r'\b(\d{1,2})[:h\.](\d{2})\b', text)
    if not time_match:
        return None

    hour = int(time_match.group(1))
    minute = int(time_match.group(2))

    # 2. Suche Datum (z. B. „morgen“, „Freitag“)
    results = search_dates(text, languages=["de"])
    if not results:
        return None

    # 3. Nimm das erste erkannte Datum (z. B. "heute", "morgen")
    base_date = results[0][1].date()

    # 4. Kombiniere beides zu einem datetime
    dt = datetime.combine(base_date, datetime.min.time()).replace(hour=hour, minute=minute)
    return tz.localize(dt)
    
def list_all_calendars():
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)
    calendars = service.calendarList().list().execute().get('items', [])
    return [(cal['summary'], cal['id']) for cal in calendars]

def get_events_for_date(target_date):
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)

    start = target_date.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(pytz.utc).isoformat()
    end = target_date.replace(hour=23, minute=59, second=59, microsecond=0).astimezone(pytz.utc).isoformat()

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

def interpret_date_naturally(text: str) -> datetime | None:
    text = text.lower()
    now = datetime.now(pytz.timezone("Europe/Berlin"))

    if "heute" in text:
        return now
    elif "übermorgen" in text:
        return now + timedelta(days=2)
    elif "morgen" in text:
        return now + timedelta(days=1)

    result = search_dates(text, languages=["de"])
    return result[0][1] if result else None
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
            summary.append(block)
    todo = get_todoist_tasks()
    if todo:
        summary.append("📝 Aufgaben:\n" + todo)
    return summary

async def send_morning_summary(bot: Bot):
    print("⏰ Sende Morgenzusammenfassung…")
    today = datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin"))
    chunks = generate_event_summary(today)
    for chunk in chunks:
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])

async def send_evening_summary(bot: Bot):
    print("🌙 Sende Abendzusammenfassung…")
    tomorrow = datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin")) + timedelta(days=1)
    chunks = generate_event_summary(tomorrow)
    for chunk in chunks:
        await bot.send_message(chat_id=CHAT_ID, text=chunk[:4000])
        pending_events = {}
pending_tasks = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hallo! Ich bin dein Assistent.")

from dateparser.search import search_dates
import pytz

from dateparser.search import search_dates
from datetime import timedelta
import pytz

def extract_datetime_strict(text: str) -> datetime | None:
    tz = pytz.timezone("Europe/Berlin")
    results = search_dates(text, languages=["de"])
    if not results:
        return None
    for match_text, dt in results:
        if re.search(r"\b\d{1,2}([:.h])\d{2}\b", match_text):  # z. B. 18:30, 18.30, 18h30
            if dt.tzinfo is None:
                return tz.localize(dt)
            else:
                return dt.astimezone(tz)
    return None
    
async def termin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    global pending_events
    user_id = update.effective_user.id
    text = update.message.text.replace("/termin", "").strip()

    dt = find_time_and_date(text)
    if not dt:
        await update.message.reply_text("❌ Konnte keine klare Uhrzeit wie 18:30 erkennen.")
        return

    end = dt + timedelta(hours=1)

    parsed = {
        "title": text.split(" um ")[0].strip().title(),  # alles vor „um“ als Titel
        "location": None,
        "start": dt,
        "end": end,
        "confirmation_text": f"Neuer Termin am {dt.strftime('%d.%m.%Y')} um {dt.strftime('%H:%M')} Uhr"
    }

    pending_events[user_id] = parsed
    await show_confirmation(update, parsed)
    
async def show_confirmation(update: Update, parsed: dict):
    message = parsed.get("confirmation_text") or (
        f"📅 Termin:\nTitel: {parsed['title']}\n"
        f"Start: {parsed['start'].strftime('%d.%m.%Y %H:%M')}\n"
        f"Ende: {parsed['end'].strftime('%d.%m.%Y %H:%M')}"
    )

    buttons = [[
        InlineKeyboardButton("✅ Ja, eintragen", callback_data="confirm"),
        InlineKeyboardButton("❌ Nein", callback_data="cancel")
    ]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    if query.data == "confirm" and user_id in pending_events:
        parsed = pending_events.pop(user_id)
        try:
            creds = load_credentials()
            service = build('calendar', 'v3', credentials=creds)
            event = {
                'summary': parsed['title'],
                'start': {'dateTime': parsed['start'].isoformat(), 'timeZone': 'Europe/Berlin'},
                'end': {'dateTime': parsed['end'].isoformat(), 'timeZone': 'Europe/Berlin'},
            }
            if parsed.get("location"):
                event['location'] = parsed["location"]
            service.events().insert(calendarId='primary', body=event).execute()
            await query.edit_message_text("✅ Termin wurde eingetragen!")
        except Exception as e:
            await query.edit_message_text("❌ Fehler beim Eintragen.")
    else:
        pending_events.pop(user_id, None)
        await query.edit_message_text("❌ Termin wurde verworfen.")

async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    headers = {"Authorization": f"Bearer {TODOIST_API_TOKEN}"}
    params = {"filter": "today | overdue"}
    r = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers, params=params)
    tasks = r.json()
    if not tasks:
        await update.message.reply_text("✅ Keine offenen Aufgaben.")
        return
    pending_tasks[update.effective_user.id] = {str(i): t for i, t in enumerate(tasks, start=1)}
    for i, task in enumerate(tasks, start=1):
        buttons = [[
            InlineKeyboardButton("✅ Einplanen", callback_data=f"plan_{i}"),
            InlineKeyboardButton("⏭️ Verschieben", callback_data=f"verschiebe_{i}"),
            InlineKeyboardButton("✔️ Erledigt", callback_data=f"done_{i}")
        ]]
        await update.message.reply_text(f"{i}. {task['content']}", reply_markup=InlineKeyboardMarkup(buttons))

async def todo_button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id
    action, number = query.data.split("_")
    task = pending_tasks.get(user_id, {}).get(number)
    if not task:
        await query.edit_message_text("⚠️ Aufgabe nicht gefunden.")
        return
    if action == "plan":
        context.user_data["plan_task"] = task
        await query.edit_message_text(f"Wann soll ich '{task['content']}' einplanen? (z.B. 14:00)")
    elif action == "verschiebe":
        task_id = task["id"]
        new_due = (datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
        requests.post(f"https://api.todoist.com/rest/v2/tasks/{task_id}",
                      headers={"Authorization": f"Bearer {TODOIST_API_TOKEN}"},
                      json={"due_date": new_due})
        await query.edit_message_text("⏭️ Aufgabe auf morgen verschoben.")
    elif action == "done":
        task_id = task["id"]
        requests.post(f"https://api.todoist.com/rest/v2/tasks/{task_id}/close",
                      headers={"Authorization": f"Bearer {TODOIST_API_TOKEN}"})
        await query.edit_message_text("✔️ Aufgabe als erledigt markiert.")


async def handle_startzeit(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    try:
        time_parsed = parser.parse(text, fuzzy=True)
        now = datetime.now(pytz.timezone("Europe/Berlin"))
        start = now.replace(hour=time_parsed.hour, minute=time_parsed.minute, second=0, microsecond=0)
        end = start + timedelta(minutes=60)
        task = context.user_data.pop("plan_task")

        creds = load_credentials()
        service = build("calendar", "v3", credentials=creds)
        event = {
            "summary": task["content"],
            "start": {"dateTime": start.isoformat(), "timeZone": "Europe/Berlin"},
            "end": {"dateTime": end.isoformat(), "timeZone": "Europe/Berlin"}
        }
        service.events().insert(calendarId="primary", body=event).execute()
        await update.message.reply_text(f"✅ '{task['content']}' wurde eingeplant: {start.strftime('%H:%M')}–{end.strftime('%H:%M')}")
    except Exception as e:
        await update.message.reply_text("❌ Konnte die Zeit nicht verstehen. Bitte gib z.B. 14:00 an.")

async def frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    date = interpret_date_naturally(text)
    if not date:
        await update.message.reply_text("❌ Konnte kein Datum erkennen.")
        return
    chunks = generate_event_summary(date)
    for chunk in chunks:
        await update.message.reply_text(chunk[:4000])

async def handle_text(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if "plan_task" in context.user_data:
        await handle_startzeit(update, context)
    else:
        await frage(update, context)

async def morning_job(context: ContextTypes.DEFAULT_TYPE):
    chat_id = 8011259706  # oder dynamisch
    class FakeUpdate:
        def __init__(self, bot, chat_id):
            self.message = type("msg", (), {
                "reply_text": lambda text: bot.send_message(chat_id, text),
                "reply_markdown": lambda text, reply_markup=None: bot.send_message(chat_id, text, parse_mode="Markdown", reply_markup=reply_markup)
            })()
    update = FakeUpdate(context.bot, chat_id)
    await mail_command(update, context)

async def post_init(application):
    await asyncio.sleep(1)
    bot = application.bot
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    scheduler.add_job(send_morning_summary, 'cron', hour=6, minute=40, args=[bot])
    scheduler.add_job(send_evening_summary, 'cron', hour=19, minute=15, args=[bot])
    scheduler.add_job(morning_job, CronTrigger(hour=7, minute=0))  # Mail-Check
    scheduler.start()
    print("✅ Scheduler gestartet.")

async def setup_application() -> Application:
    app = Application.builder().token(BOT_TOKEN).post_init(post_init).build()
    await app.bot.delete_webhook(drop_pending_updates=True)
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("termin", termin))
    app.add_handler(CommandHandler("todo", todo))
    app.add_handler(CommandHandler("frage", frage))
    app.add_handler(CommandHandler("mail", mail_command))
    app.add_handler(CallbackQueryHandler(mail_callback_handler, pattern="^(archive|defer):"))
    app.add_handler(CallbackQueryHandler(todo_button_handler, pattern="^(plan|verschiebe|done)_"))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_text))
    return app


if __name__ == "__main__":
    import asyncio

    async def runner():
        print(\"✅ Bot gestartet – warte auf Nachrichten...\")
        app = await setup_application()
        await app.initialize()
        await app.start()
        await asyncio.Event().wait()  # blockiere dauerhaft

    asyncio.run(runner())
