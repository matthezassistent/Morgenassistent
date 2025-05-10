import datetime
import pytz
import pickle
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from googleapiclient.discovery import build

# === Google Calendar Service laden ===
def get_calendar_service():
    with open("token.pkl", "rb") as token:
        creds = pickle.load(token)
    return build("calendar", "v3", credentials=creds)

# === Handlerfunktion für heute ===
async def kalender_heute(update: Update, context: ContextTypes.DEFAULT_TYPE):
    tz = pytz.timezone("Europe/Berlin")
    now = datetime.datetime.now(tz)
    start_of_day = now.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    end_of_day = now.replace(hour=23, minute=59, second=59, microsecond=999999).isoformat()

    try:
        service = get_calendar_service()
        calendar_list = service.calendarList().list().execute()
        events_output = []

        for cal in calendar_list.get("items", []):
            events_result = service.events().list(
                calendarId=cal["id"],
                timeMin=start_of_day,
                timeMax=end_of_day,
                singleEvents=True,
                orderBy="startTime"
            ).execute()

            events = events_result.get("items", [])
            if events:
                events_output.append(f"**{cal.get('summary')}**:")
                for event in events:
                    start = event["start"].get("dateTime", event["start"].get("date"))
                    title = event.get("summary", "(kein Titel)")
                    events_output.append(f"  - {start}: {title}")
        
        if events_output:
            await update.message.reply_text("\n".join(events_output))
        else:
            await update.message.reply_text("Heute stehen keine Termine an.")
    except Exception as e:
        await update.message.reply_text(f"Fehler beim Laden des Kalenders:\n{e}")

# === Handlerliste ===
calendar_handlers = [
    CommandHandler("kalenderheute", kalender_heute)
]
