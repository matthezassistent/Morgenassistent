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
import requests
from bs4 import BeautifulSoup
import datetime
import time


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
    
import requests
from bs4 import BeautifulSoup
import datetime

def get_next_trains():
    try:
        url = "https://fahrplan.oebb.at/bin/stboard.exe/dn?input=Hallein&boardType=dep&start=yes"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        response = requests.get(url, headers=headers)
        response.raise_for_status()

        soup = BeautifulSoup(response.text, "html.parser")

        rows = soup.select("table.result tbody tr.journey")
        trains = []

        now = datetime.datetime.now()

        for row in rows:
            time_cell = row.find("td", class_="time")
            station_cell = row.find("td", class_="station")
            route_cell = row.find("td", class_="route")

            if not time_cell or not station_cell or not route_cell:
                continue

            dep_time_text = time_cell.get_text(strip=True)
            destination = station_cell.get_text(strip=True)
            via_text = route_cell.get_text(strip=True).lower()

            try:
                dep_time = datetime.datetime.strptime(dep_time_text, "%H:%M").replace(
                    year=now.year, month=now.month, day=now.day
                )
            except Exception:
                continue

            delta = (dep_time - now).total_seconds() / 60

            if 0 <= delta <= 45:
                # Prüfen: fährt entweder direkt nach Salzburg oder via Salzburg
                if "salzburg hbf" in destination.lower() or "salzburg" in via_text:
                    trains.append(f"**{dep_time.strftime('%H:%M')}** ➔ {destination}")

        if not trains:
            return "🚆 **Keine passenden Züge Richtung Salzburg in den nächsten 45 Minuten gefunden.**"

        result = "🚆 **Nächste Verbindungen Hallein → Salzburg Hbf:**\n\n"
        result += "\n".join(trains)
        return result

    except Exception as e:
        return f"⚠️ Fehler beim Zug-Update:\n{e}"

# ✅ /termin Befehl: Flexible Sprache + Bestätigung

from telegram import InlineKeyboardButton, InlineKeyboardMarkup

pending_events = {}  # Zwischenspeicher für Benutzeranfragen

async def parse_event(text):
    try:
        # Einfache Heuristik: Erkennung von Zeit und Datum
        found_dates = search_dates(text, languages=['de'])
        if not found_dates:
            return None

        # Erste gefundene Zeit/Daten nehmen
        start_dt = found_dates[0][1]

        # Suche nach Zeitraum, falls angegeben (z.B. 16:00-18:00)
        if "-" in text:
            times = text.split("-")
            if len(times) >= 2:
                try:
                    start_time = parser.parse(times[0], fuzzy=True)
                    end_time = parser.parse(times[1], fuzzy=True)
                    start_dt = start_dt.replace(hour=start_time.hour, minute=start_time.minute)
                    end_dt = start_dt.replace(hour=end_time.hour, minute=end_time.minute)
                except:
                    end_dt = start_dt + datetime.timedelta(hours=1)
            else:
                end_dt = start_dt + datetime.timedelta(hours=1)
        else:
            end_dt = start_dt + datetime.timedelta(hours=1)

        # Ort erkennen (alles nach "in" oder "bei")
        ort = None
        if " in " in text:
            ort = text.split(" in ")[-1]
        elif " bei " in text:
            ort = text.split(" bei ")[-1]

        # Titel aus Text extrahieren (ganz grob)
        title = text.split(" findet")[0] if " findet" in text else text.split(" am")[0]

        return {
            "title": title.strip(),
            "start": start_dt,
            "end": end_dt,
            "location": ort.strip() if ort else None
        }
    except Exception as e:
        print(f"⚠️ Fehler beim Parsen: {e}")
        return None

async def termin(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    text = update.message.text.replace("/termin", "").strip()

    parsed = await parse_event(text)
    if not parsed:
        await update.message.reply_text("❌ Konnte den Termin nicht verstehen. Bitte genaue Angaben machen.")
        return

    # Speichern im pending_events
    pending_events[user_id] = parsed

    # Zusammenfassung
    message = f"📅 **Geplanter Termin:**\n\nTitel: {parsed['title']}\nStart: {parsed['start'].strftime('%d.%m.%Y %H:%M')}\nEnde: {parsed['end'].strftime('%d.%m.%Y %H:%M')}"
    if parsed.get("location"):
        message += f"\nOrt: {parsed['location']}"

    # Bestätigungs-Buttons
    buttons = [
        [InlineKeyboardButton("✅ Ja, eintragen", callback_data="confirm"),
         InlineKeyboardButton("❌ Nein, abbrechen", callback_data="cancel")]
    ]
    reply_markup = InlineKeyboardMarkup(buttons)

    await update.message.reply_text(message, reply_markup=reply_markup, parse_mode="Markdown")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    user_id = query.from_user.id

    if query.data == "confirm" and user_id in pending_events:
        parsed = pending_events.pop(user_id)

        try:
            # Eintrag in Google Kalender
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
            await query.edit_message_text("✅ Termin wurde erfolgreich in deinen Kalender eingetragen!")
        except Exception as e:
            print(f"❌ Fehler beim Eintragen: {e}")
            await query.edit_message_text("❌ Fehler beim Eintragen des Termins.")
    else:
        if user_id in pending_events:
            pending_events.pop(user_id)
        await query.edit_message_text("❌ Termin wurde verworfen.")

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
    try:
        message = get_next_trains()
        await update.message.reply_text(message, parse_mode="Markdown")
    except Exception as e:
        await update.message.reply_text(f"⚠️ Fehler bei der Zugabfrage:\n{e}")
        
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
    message = get_next_trains()
    await bot.send_message(chat_id=CHAT_ID, text=message, parse_mode="Markdown")
    
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
    app.add_handler(CommandHandler("termin", termin))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, frage))
    app.add_handler(telegram.ext.CallbackQueryHandler(button_handler))
if __name__ == '__main__':
    main()
