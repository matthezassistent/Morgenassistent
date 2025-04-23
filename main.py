import os
import base64
import datetime
import pickle
import dateparser
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

# Chat GPT abfrage

def generate_chatgpt_briefing(summary):
    if not OPENAI_API_KEY:
        return None

    try:
        openai.api_key = OPENAI_API_KEY
        response = openai.ChatCompletion.create(
            model="gpt-4",
            messages=[
                {
                    "role": "system",
                    "content": (
                        "Du bist ein intelligenter Assistent, der kurze, prägnante Briefings für Kalendereinträge erstellt. "
                        "Wenn der Eintrag z. B. ein Musikstück oder eine historische Figur erwähnt, gib eine hilfreiche, "
                        "2-sätzige Einordnung für eine gut vorbereitete Besprechung oder Unterrichtssituation."
                    )
                },
                {
                    "role": "user",
                    "content": f"Gib mir ein kurzes Briefing zu diesem Kalendereintrag: '{summary}'"
                }
            ],
            max_tokens=100,
            temperature=0.7
        )
        return response.choices[0].message["content"].strip()
    except Exception as e:
        return f"(GPT-Fehler: {str(e)})"

# ✅ Zugang zum Kalender
def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

# ✅ Termin zum Kalender hinzufügen
def add_event_to_calendar(summary, start_time, end_time):
    try:
        creds = load_credentials()
        service = build('calendar', 'v3', credentials=creds)
        event = {
            'summary': summary,
            'start': {'dateTime': start_time.isoformat(), 'timeZone': 'Europe/Berlin'},
            'end': {'dateTime': end_time.isoformat(), 'timeZone': 'Europe/Berlin'}
        }
        event = service.events().insert(calendarId='primary', body=event).execute()
        return f"✅ Termin hinzugefügt: {event.get('summary')}"
    except HttpError as error:
        return f"❌ Fehler beim Hinzufügen des Termins: {error}"

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

# ✅ Aufgabe zu Todoist hinzufügen
def add_task_to_todoist(content, due_string="today"):
    try:
        headers = {
            "Authorization": f"Bearer {TODOIST_API_TOKEN}"
        }
        data = {
            "content": content,
            "due_string": due_string
        }
        response = requests.post("https://api.todoist.com/rest/v2/tasks", json=data, headers=headers)
        if response.status_code in [200, 204]:
            return "✅ Aufgabe wurde zu Todoist hinzugefügt."
        else:
            return f"❌ Fehler beim Hinzufügen zu Todoist: {response.text}"
    except Exception as e:
        return f"❌ Ausnahme beim Hinzufügen zu Todoist: {e}"

# Todoist auflisten

def get_todoist_tasks():
    try:
        headers = {
            "Authorization": f"Bearer {TODOIST_API_TOKEN}"
        }
        params = {
            "filter": "today | overdue"
        }
        response = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers, params=params)
        if response.status_code != 200:
            return f"❌ Fehler beim Abrufen der Aufgaben: {response.text}"

        tasks = response.json()
        if not tasks:
            return "✅ Keine Aufgaben für heute oder überfällig."
        
        result = "📝 Aufgaben für heute / überfällig:\n\n"
        for task in tasks:
            due = task.get("due", {}).get("string", "kein Datum")
            result += f"- {task['content']} ({due})\n"
        return result

    except Exception as e:
        return f"❌ Fehler beim Abrufen der Aufgaben: {e}"

# ✅ Ausgabe generieren mit optionalem GPT-Briefing
def generate_event_summary(date: datetime.datetime):
    calendars_with_events = get_events_for_date(date)
    if not calendars_with_events:
        response = f"📅 Keine Termine am {date.strftime('%d.%m.%Y')}."
    else:
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
                briefing = generate_chatgpt_briefing(summary)
                response += f"- {start_time}: {summary}\n"
                if briefing:
                    response += f"  💬 {briefing}\n"
            response += "\n"

    # Todoist-Teil hinzufügen
    todo_response = get_todoist_tasks()
    response += "\n" + todo_response

    return response


# ✅ Telegram-Kommandos
async def frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        text = update.message.text.strip().lower()

        # Sonderbegriffe manuell behandeln
        if "nächste woche" in text:
            today = datetime.datetime.now()
            next_monday = today + datetime.timedelta(days=(7 - today.weekday()))
            await send_events_for_date(update, next_monday)
            return

        if "dieses wochenende" in text:
            today = datetime.datetime.now()
            saturday = today + datetime.timedelta((5 - today.weekday()) % 7)
            await send_events_for_date(update, saturday)
            return

        if "demnächst" in text or "bald" in text:
            date = datetime.datetime.now() + datetime.timedelta(days=2)
            await send_events_for_date(update, date)
            return

        # Standard-NLP mit dateparser
        results = search_dates(text, languages=['de'])
        if not results:
            await update.message.reply_text("❌ Ich konnte kein Datum erkennen.")
            return

        parsed_date = results[0][1]
        parsed_date = parsed_date.replace(hour=0, minute=0, second=0, microsecond=0)

        await send_events_for_date(update, parsed_date)

    except Exception as e:
        await update.message.reply_text(f"⚠️ Fehler beim Verarbeiten deiner Anfrage:\n{e}")

# ✅ Neue Funktion zum Hinzufügen von Todoist-Aufgaben über Befehl
async def add_todoist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    content = update.message.text.replace("/todo ", "").strip()
    if not content:
        await update.message.reply_text("❗ Gib bitte den Inhalt der Aufgabe an: /todo [Aufgabe]")
        return
    result = add_task_to_todoist(content)
    await update.message.reply_text(result)

# zusatz von todoist
async def list_todoist(update: Update, context: ContextTypes.DEFAULT_TYPE):
    result = get_todoist_tasks()
    await update.message.reply_text(result)

# ✅ Neue Funktion zum Hinzufügen von Kalender-Terminen über Befehl
async def add_event(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.replace("/termin ", "").strip()
    parts = text.split(" | ")
    if len(parts) < 3:
        await update.message.reply_text("❗ Format: /termin Titel | 2025-05-01 14:00 | 2025-05-01 15:00")
        return
    summary, start_str, end_str = parts
    try:
        start_dt = parser.parse(start_str)
        end_dt = parser.parse(end_str)
        result = add_event_to_calendar(summary, start_dt, end_dt)
        await update.message.reply_text(result)
    except Exception as e:
        await update.message.reply_text(f"❌ Fehler beim Erstellen des Termins: {e}")

async def send_events_for_date(update: Update, date: datetime.datetime):
    summary = generate_event_summary(date)
    await update.message.reply_text(summary)

# ✅ Scheduler-Funktionen für automatische Nachrichten
async def send_daily_summary(bot: Bot):
    today = datetime.datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin"))
    message = generate_event_summary(today)
    await bot.send_message(chat_id=CHAT_ID, text=f"Guten Morgen ☀️\n\n{message}")

async def send_evening_summary(bot: Bot):
    tomorrow = datetime.datetime.utcnow().astimezone(pytz.timezone("Europe/Berlin")) + datetime.timedelta(days=1)
    message = generate_event_summary(tomorrow)
    await bot.send_message(chat_id=CHAT_ID, text=f"Gute Nacht 🌙 Hier ist die Vorschau für morgen: {message}")

async def post_init(application):
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    bot = application.bot
    scheduler.add_job(send_daily_summary, 'cron', hour=7, minute=0, args=[bot])
    scheduler.add_job(send_evening_summary, 'cron', hour=21, minute=0, args=[bot])
    scheduler.start()
    print("🕒 Scheduler gestartet")

# ✅ Bot starten

def main():
    print("👀 Bot gestartet und wartet auf Nachrichten.")

    app = ApplicationBuilder().token(BOT_TOKEN).post_init(post_init).build()

    # Handler für Telegram-Befehle
    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("tomorrow", tomorrow))
    app.add_handler(CommandHandler("todo", add_todoist))
    app.add_handler(CommandHandler("termin", add_event))
    app.add_handler(CommandHandler("todos", list_todoist))  # falls du den eingebaut hast

    # Alle anderen Textnachrichten
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, frage))

    # Bot starten (Polling-Modus)
    app.run_polling()
if __name__ == '__main__':
    main()
