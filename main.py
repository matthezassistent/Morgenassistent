
import os
import base64
import pickle
import re
import datetime
import pytz
import requests
import asyncio
import nest_asyncio
from openai import OpenAI

OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=OPENAI_API_KEY)

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
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# ENV
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = 8011259706
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
PORT = int(os.environ.get("PORT", 8443))

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
                briefing = generate_gpt_briefing(e.get('summary', ''))
                if briefing:
                    block += f"\n  💬 {briefing}"
            summary.append(block)
    todo = get_todoist_tasks()
    if todo:
        summary.append("📝 Aufgaben:\n" + todo)
    return summary

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

# ============================
# Telegram Handler & Logik
# ============================

pending_events = {}
pending_tasks = {}

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("👋 Hallo! Ich bin dein Assistent.")

async def parse_event(text):
    try:
        found_dates = search_dates(text, languages=['de'])
        if not found_dates:
            return None
        start_dt = found_dates[0][1]
        if "-" in text:
            times = text.split("-")
            try:
                start_time = parser.parse(times[0], fuzzy=True)
                end_time = parser.parse(times[1], fuzzy=True)
                start_dt = start_dt.replace(hour=start_time.hour, minute=start_time.minute)
                end_dt = start_dt.replace(hour=end_time.hour, minute=end_time.minute)
            except:
                end_dt = start_dt + datetime.timedelta(hours=1)
        else:
            end_dt = start_dt + datetime.timedelta(hours=1)
        ort = None
        if " in " in text:
            ort = text.split(" in ")[-1]
        elif " bei " in text:
            ort = text.split(" bei ")[-1]
        title = text.split(" findet")[0] if " findet" in text else text.split(" am")[0]
        return {
            "title": title.strip(),
            "start": start_dt,
            "end": end_dt,
            "location": ort.strip() if ort else None
        }
    except:
        return None

async def termin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.replace("/termin", "").strip()
    parsed = await parse_event(text)
    if not parsed:
        await update.message.reply_text("❌ Konnte den Termin nicht verstehen.")
        return
    pending_events[user_id] = parsed
    message = f"📅 **Geplanter Termin:**\n\nTitel: {parsed['title']}\nStart: {parsed['start'].strftime('%d.%m.%Y %H:%M')}\nEnde: {parsed['end'].strftime('%d.%m.%Y %H:%M')}"
    if parsed.get("location"):
        message += f"\nOrt: {parsed['location']}"
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
        new_due = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
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
        now = datetime.datetime.now(pytz.timezone("Europe/Berlin"))
        start = now.replace(hour=time_parsed.hour, minute=time_parsed.minute, second=0, microsecond=0)
        end = start + datetime.timedelta(minutes=60)
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

async def post_init(application):
    await asyncio.sleep(1)
    bot = application.bot
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    scheduler.add_job(send_morning_summary, 'cron', hour=6, minute=40, args=[bot])
    scheduler.add_job(send_evening_summary, 'cron', hour=22, minute=30, args=[bot])
    scheduler.start()
    print("✅ Scheduler gestartet.")

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

if __name__ == '__main__':
    nest_asyncio.apply()
    loop = asyncio.get_event_loop()
    app = loop.run_until_complete(setup_application())
    app.run_polling()
