import os
import base64
import pickle
import re
import datetime
import pytz
import requests
import asyncio
import openai
import telegram
from datetime import datetime, timedelta, date, time
from dateutil import parser
from dateparser.search import search_dates
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from telegram import Update, Bot, InlineKeyboardButton, InlineKeyboardMarkup, ReplyKeyboardMarkup
print("PTB-Version:", telegram.__version__)
from telegram.ext import (
    ApplicationBuilder,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    CallbackQueryHandler,
    filters,
    Application
)

# ENV-VARIABLEN
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = 8011259706
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")
PORT = int(os.environ.get("PORT", 8443))
# Webhook-Konfiguration (nur sichere Variante)
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET")
RENDER_URL = os.getenv("RENDER_URL")
if not WEBHOOK_SECRET or not RENDER_URL:
    raise RuntimeError("❌ WEBHOOK_SECRET oder RENDER_URL ist nicht gesetzt!")
webhook_url = f"{RENDER_URL}/{WEBHOOK_SECRET}"

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
        events = service.events().list(
            calendarId=cal_id,
            timeMin=start,
            timeMax=end,
            singleEvents=True,
            orderBy='startTime'
        ).execute().get('items', [])
        if events:
            events_all.append((name, events))
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
    except:
        return None

# Todoist

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

def get_todoist_tasks_with_duration():
    headers = {"Authorization": f"Bearer {TODOIST_API_TOKEN}"}
    params = {"filter": "today | overdue"}
    r = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers, params=params)
    if r.status_code != 200:
        return []
    tasks = r.json()
    return [{'content': t['content'], 'duration': parse_task_duration(t['content'])} for t in tasks]

def parse_task_duration(task_content):
    match = re.search(r"#(\d+)min", task_content)
    return int(match.group(1)) if match else 30

# Termin-Parser (/termin)

pending_events = {}

async def parse_event(text):
    try:
        found_dates = search_dates(text, languages=['de'])
        if not found_dates:
            return None
        start_dt = found_dates[0][1]
        if "-" in text:
            times = text.split("-")
            if len(times) >= 2:
                try:
                    start_time = parser.parse(times[0], fuzzy=True)
                    end_time = parser.parse(times[1], fuzzy=True)
                    start_dt = start_dt.replace(hour=start_time.hour, minute=start_time.minute)
                    end_dt = start_dt.replace(hour=end_time.hour, minute=end_time.minute)
                except:
                    end_dt = start_dt + timedelta(hours=1)
            else:
                end_dt = start_dt + timedelta(hours=1)
        else:
            end_dt = start_dt + timedelta(hours=1)
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
    buttons = [[InlineKeyboardButton("✅ Ja, eintragen", callback_data="confirm"), InlineKeyboardButton("❌ Nein", callback_data="cancel")]]
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
        if user_id in pending_events:
            pending_events.pop(user_id)
        await query.edit_message_text("❌ Termin wurde verworfen.")

# Tagesplanung (/planung)

def get_busy_times(creds, start_time, end_time):
    service = build("calendar", "v3", credentials=creds)
    calendar_ids = [cal[1] for cal in list_all_calendars()]
    items = [{"id": cal_id} for cal_id in calendar_ids]
    body = {"timeMin": start_time.isoformat() + "Z", "timeMax": end_time.isoformat() + "Z", "items": items}
    events_result = service.freebusy().query(body=body).execute()
    busy_times = []
    for cal_id in calendar_ids:
        busy_times += events_result["calendars"][cal_id]["busy"]
    return sorted(busy_times, key=lambda x: x["start"])

def find_free_blocks(busy_times, start_dt, end_dt):
    free = []
    current = start_dt
    for busy in busy_times:
        busy_start = datetime.fromisoformat(busy["start"].replace("Z", "+00:00"))
        busy_end = datetime.fromisoformat(busy["end"].replace("Z", "+00:00"))
        if current < busy_start:
            free.append((current, busy_start))
        current = max(current, busy_end)
    if current < end_dt:
        free.append((current, end_dt))
    return free

def plan_tasks_in_blocks(tasks, free_blocks):
    plan = []
    remaining = tasks.copy()
    for start, end in free_blocks:
        slot = start
        while remaining and slot + timedelta(minutes=remaining[0]['duration']) <= end:
            task = remaining.pop(0)
            plan.append({
                'task': task['content'],
                'start': slot,
                'end': slot + timedelta(minutes=task['duration'])
            })
            slot += timedelta(minutes=task['duration'])
    return plan, remaining

def yes_no_keyboard():
    return ReplyKeyboardMarkup([["Ja", "Nein"]], one_time_keyboard=True, resize_keyboard=True)

async def planung(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("🧠 Ich plane deinen Tag…")
    creds = load_credentials()
    now = datetime.utcnow()
    end = now.replace(hour=18, minute=0)
    tasks = get_todoist_tasks_with_duration()
    busy = get_busy_times(creds, now, end)
    free = find_free_blocks(busy, now, end)
    plan, remaining = plan_tasks_in_blocks(tasks, free)
    msg = "📋 Vorschlag für deine Aufgabenplanung:\n"
    for item in plan:
        msg += f"{item['start'].strftime('%H:%M')} – {item['end'].strftime('%H:%M')}: {item['task']}\n"
    if remaining:
        msg += "\n🕓 Diese Aufgaben würde ich auf morgen verschieben:\n"
        for r in remaining:
            msg += f"• {r['content']}\n"
    msg += "\nSoll ich das so eintragen?"
    await update.message.reply_text(msg, reply_markup=yes_no_keyboard())
    context.user_data["geplanter_plan"] = plan

async def handle_yes_no(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip().lower()
    if text == "ja" and "geplanter_plan" in context.user_data:
        plan = context.user_data.pop("geplanter_plan")
        creds = load_credentials()
        service = build("calendar", "v3", credentials=creds)
        for item in plan:
            event = {
                'summary': item['task'],
                'start': {'dateTime': item['start'].isoformat(), 'timeZone': 'Europe/Berlin'},
                'end': {'dateTime': item['end'].isoformat(), 'timeZone': 'Europe/Berlin'}
            }
            service.events().insert(calendarId='primary', body=event).execute()
        await update.message.reply_text("✅ Planung wurde eingetragen.")
    elif text == "nein":
        context.user_data.pop("geplanter_plan", None)
        await update.message.reply_text("❌ Planung verworfen.")

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

# Start

def main():
    print("🚀 Starte Telegram Webhook-Bot...")
    global app
    app = ApplicationBuilder().token(BOT_TOKEN).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("planung", planung))
    app.add_handler(CommandHandler("termin", termin))
    app.add_handler(MessageHandler(filters.TEXT & filters.Regex("^(Ja|Nein|ja|nein)$"), handle_yes_no))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, frage))
    app.add_handler(CallbackQueryHandler(button_handler))
    app.run_webhook(
        listen="0.0.0.0",
        port=PORT,
        webhook_url=f"{RENDER_URL}/{WEBHOOK_SECRET}"
    )
   
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("-> /start empfangen")
    await update.message.reply_text("👋 Hallo! Ich bin dein Assistent.")

if __name__ == '__main__':
    main()
