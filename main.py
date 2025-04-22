import os
import datetime
import pickle
from telegram.ext import Updater, CommandHandler
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials

# Telegram Bot Token aus Umgebungsvariable
BOT_TOKEN = os.getenv("BOT_TOKEN")

# Kalender-TOKEN laden
def load_credentials():
    with open("token.pkl", "rb") as token_file:
        creds = pickle.load(token_file)
    return creds

# Kalender-Abfrage für morgen
def get_tomorrows_events():
    creds = load_credentials()
    service = build('calendar', 'v3', credentials=creds)

    now = datetime.datetime.utcnow()
    tomorrow = now + datetime.timedelta(days=1)
    start = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 0, 0, 0).isoformat() + 'Z'
    end = datetime.datetime(tomorrow.year, tomorrow.month, tomorrow.day, 23, 59, 59).isoformat() + 'Z'

    events_result =_
