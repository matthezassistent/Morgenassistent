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
import asyncio

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

# ✅ Schulferientage in Salzburg 2025 (manuell gepflegt)
FERIENTAGE = [
    (datetime.date(2025, 2, 10), datetime.date(2025, 2, 15)),  # Semesterferien
    (datetime.date(2025, 4, 12), datetime.date(2025, 4, 21)),  # Osterferien
    (datetime.date(2025, 6, 7), datetime.date(2025, 6, 9)),    # Pfingsten
    (datetime.date(2025, 7, 5), datetime.date(2025, 9, 7)),    # Sommerferien
    (datetime.date(2025, 10, 27), datetime.date(2025, 10, 31)),# Herbstferien
    (datetime.date(2025, 12, 24), datetime.date(2026, 1, 6)),  # Weihnachtsferien
]

def ist_schultag():
    heute = datetime.date.today()
    if heute.weekday() >= 5:  # Samstag (5), Sonntag (6)
        return False
    for start, ende in FERIENTAGE:
        if start <= heute <= ende:
            return False
    return True

# ✅ Zugstatus aus ÖBB Scotty API holen

def get_train_status():
    try:
        url = "https://fahrplan.oebb.at/bin/query.exe/dn"
        headers = {
            "User-Agent": "Mozilla/5.0"
        }
        payloads = [
            {"from": "Hallein", "to": "Salzburg Hbf", "time": "06:59", "date": datetime.date.today().strftime("%d.%m.%Y")},
            {"from": "Hallein", "to": "Salzburg Hbf", "time": "07:04", "date": datetime.date.today().strftime("%d.%m.%Y")},
        ]

        results = []

        for payload in payloads:
            params = {
                "input": payload["from"],
                "boardType": "dep",
                "time": payload["time"],
                "date": payload["date"],
                "REQ0JourneyStopsS0A": "1",
                "REQ0JourneyStopsZ0A": "1",
                "REQ0JourneyStopsS0ID": "A=1@L=000000000@",
                "REQ0JourneyStopsZ0ID": "A=1@L=000000000@",
                "REQ0HafasSearchForw": "1",
                "REQ0JourneyProduct_prod_list": "11:1111111111111111",
                "start": "Suchen"
            }
            response = requests.get(url, params=params, headers=headers)

            if response.status_code == 200:
                text = response.text
                if "verspätet" in text:
                    delay = "verspätet"
                elif "pünktlich" in text:
                    delay = "pünktlich"
                else:
                    delay = "keine Info"

                gleis = "?"
                if "Gleis" in text:
                    try:
                        gleis = text.split("Gleis ")[1].split("<")[0]
                    except:
                        pass

                results.append(f"- {payload['time']} ab Hallein: {delay} (Gleis {gleis})")
            else:
                results.append(f"- {payload['time']} ab Hallein: Fehler beim Abruf")

        return results

    except Exception as e:
        return [f"Fehler bei der Zugabfrage: {e}"]

# ✅ Nachricht senden

async def send_train_update(bot: Bot):
    if not ist_schultag():
        print("🚫 Kein Schultag – keine Zuginfo gesendet.")
        return

    statusliste = get_train_status()
    message = "🚆 Zugstatus für heute:\n\n" + "\n".join(statusliste)
    await bot.send_message(chat_id=CHAT_ID, text=message)

# ✅ Scheduler-Integration

async def send_daily_summary(bot: Bot):
    today = datetime.datetime.utcnow().astimezone(datetime.timezone(datetime.timedelta(hours=2)))
    await bot.send_message(chat_id=CHAT_ID, text=f"Guten Morgen ☀️\n\nNoch keine Aufgaben geladen.")

async def send_evening_summary(bot: Bot):
    tomorrow = datetime.datetime.utcnow().astimezone(datetime.timezone(datetime.timedelta(hours=2))) + datetime.timedelta(days=1)
    await bot.send_message(chat_id=CHAT_ID, text=f"Gute Nacht 🌙 Hier ist die Vorschau für morgen:\n\nNoch keine Termine geladen.")

async def post_init(application):
    await asyncio.sleep(1)  # Warten, bis run_polling sicher gestartet ist
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")
    bot = application.bot
    scheduler.add_job(send_daily_summary, 'cron', hour=7, minute=0, args=[bot])
    scheduler.add_job(send_evening_summary, 'cron', hour=21, minute=0, args=[bot])
    scheduler.add_job(send_train_update, 'cron', hour=6, minute=30, args=[bot])
    scheduler.add_job(send_train_update, 'cron', hour=6, minute=40, args=[bot])
    scheduler.start()
    print("🕒 Scheduler gestartet")
