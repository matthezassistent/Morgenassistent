import os
import asyncio
import base64
import pickle
import datetime
import pytz
import requests

from mail_handler import check_mail_status, create_mail_check_task
from apscheduler.triggers.cron import CronTrigger
from telegram import Update, Bot
from typing import List, Tuple
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
from openai import AsyncOpenAI

client = AsyncOpenAI(api_key=os.getenv("OPENAI_API_KEY"))

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
# === Kalenderintegration ===
def get_calendar_events(start, end):
    with open("token.pkl", "rb") as token:
        creds = pickle.load(token)
    service = build("calendar", "v3", credentials=creds)

    events_output = []
    calendar_list = service.calendarList().list().execute()

    for cal in calendar_list.get("items", []):
        cal_name = cal.get("summary", "(kein Name)")
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
            start_time = event.get("start", {}).get("dateTime") or event.get("start", {}).get("date")
            end_time = event.get("end", {}).get("dateTime") or event.get("end", {}).get("date")
            events_output.append({
                "summary": title,
                "start": start_time,
                "end": end_time,
                "calendar": cal_name
            })

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
            grouped = {}
            for e in events:
                cal = e.get("calendar", "Unbekannt")
                grouped.setdefault(cal, []).append(e)

            msg = f"🗓️ Termine heute ({start.strftime('%A, %d.%m.%Y')}):\n"
            for cal_name, evts in grouped.items():
                msg += f"\n📘 {cal_name}:\n"
                for e in evts:
                    start_str = e['start'][11:16] if 'T' in e['start'] else ''
                    end_str = e['end'][11:16] if 'T' in e['end'] else ''
                    zeit = f"{start_str}-{end_str}" if start_str and end_str else "(ganztägig)"
                    msg += f"- {zeit} {e['summary']}\n"
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

        tagestext = f"🗓️ {start.strftime('%A, %d.%m.%Y')}:\n"

        if events:
            grouped = {}
            for e in events:
                cal = e.get("calendar", "Unbekannt")
                grouped.setdefault(cal, []).append(e)

            for cal_name, evts in grouped.items():
                tagestext += f"\n📘 {cal_name}:\n"
                for e in evts:
                    start_str = e['start'][11:16] if 'T' in e['start'] else ''
                    end_str = e['end'][11:16] if 'T' in e['end'] else ''
                    zeit = f"{start_str}-{end_str}" if start_str and end_str else "(ganztägig)"
                    tagestext += f"- {zeit} {e['summary']}\n"
        else:
            tagestext += "Keine Termine.\n"

        # 📌 Todoist-Aufgaben ergänzen
        aufgaben = get_relevant_tasks(start.date())
        tagestext += "\n📝 Aufgaben:\n" + "\n".join(aufgaben)

        antworten.append(tagestext)

    await update.message.reply_text("\n\n".join(antworten))

# Todoist

async def todo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("✅ /todo empfangen")

    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        await update.message.reply_text("❌ Kein Todoist-Token gefunden.")
        return

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers)
        response.raise_for_status()
        tasks = response.json()

        if not tasks:
            msg = "✅ Keine offenen Aufgaben."
        else:
            msg = "📝 Offene Aufgaben:\n"
            for task in tasks:
                content = task.get("content", "(kein Titel)")
                msg += f"- [ ] {content}\n"

        await update.message.reply_text(msg)

    except Exception as e:
        await update.message.reply_text(f"❌ Fehler beim Abrufen der Aufgaben:\n{e}")
        
# todoist versammeln für update
def get_relevant_tasks(start_date: datetime.date):
    token = os.getenv("TODOIST_API_TOKEN")
    if not token:
        return ["❌ Kein Todoist-Token gefunden."]

    headers = {
        "Authorization": f"Bearer {token}"
    }

    try:
        response = requests.get("https://api.todoist.com/rest/v2/tasks", headers=headers)
        response.raise_for_status()
        tasks = response.json()

        relevant = []
        for task in tasks:
            due = task.get("due", {})
            due_date_str = due.get("date") if due else None
            if due_date_str:
                try:
                    due_date = datetime.date.fromisoformat(due_date_str[:10])
                except ValueError:
                    continue
                if due_date != start_date:
                    continue
            content = task.get("content", "(kein Titel)")
            relevant.append(f"- [ ] {content}")

        return relevant if relevant else ["✅ Keine Aufgaben für diesen Tag."]

    except Exception as e:
        return [f"❌ Fehler beim Laden der Todoist-Aufgaben:\n{e}"]

import datetime
import requests

async def ripple_sec_news_check():
    # 📆 Dynamisches Datum/Zeit
    now = datetime.datetime.now().strftime("%d.%m.%Y, %H:%M")

    # 📊 Hole Live-Preise von CoinGecko
    try:
        price_response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ripple,hedera-hashgraph,solana,bitcoin,ethereum", "vs_currencies": "usd"}
        )
        prices = price_response.json()
        preis_xrp = prices["ripple"]["usd"]
        preis_hbar = prices["hedera-hashgraph"]["usd"]
        preis_sol = prices["solana"]["usd"]
        preis_btc = prices["bitcoin"]["usd"]
        preis_eth = prices["ethereum"]["usd"]
    except Exception as e:
        print("Fehler beim Abrufen der Preise:", e)
        return

    # 🧠 GPT-News-Zusammenfassung
    prompt = (
        "Was gibt es Neues im Rechtsstreit zwischen Ripple (XRP) und der SEC? "
        "Nur relevante Entwicklungen der letzten 12–24 Stunden. "
        "Wenn nichts Relevantes, antworte exakt: 'Keine relevanten Updates.'"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Du bist ein sachlicher Nachrichten-Assistent."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=400,
        )
        update = response.choices[0].message.content.strip()
    except Exception as e:
        print("Fehler bei GPT-Antwort:", e)
        return

    # 📲 Telegram-Nachricht formatieren
    message = (
        f"📢 *Ripple & XRP Update – {now}*\n\n"
        f"- *Kurs:* XRP bei {preis_xrp} USD\n"
        f"- *News:* {update}\n\n"
        "🪙 *Weitere Kurse:*\n"
        f"- HBAR: {preis_hbar} USD\n"
        f"- SOL: {preis_sol} USD\n"
        f"- BTC: {preis_btc} USD\n"
        f"- ETH: {preis_eth} USD"
    )

    if "Keine relevanten Updates" not in update:
        await send_telegram_message(message)

from telegram import Update
from telegram.ext import ContextTypes

async def xrp_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    now = datetime.datetime.now().strftime("%d.%m.%Y, %H:%M")

    # Preise abrufen
    try:
        price_response = requests.get(
            "https://api.coingecko.com/api/v3/simple/price",
            params={"ids": "ripple,hedera-hashgraph,solana,bitcoin,ethereum", "vs_currencies": "usd"}
        )
        prices = price_response.json()
        preis_xrp = prices["ripple"]["usd"]
        preis_hbar = prices["hedera-hashgraph"]["usd"]
        preis_sol = prices["solana"]["usd"]
        preis_btc = prices["bitcoin"]["usd"]
        preis_eth = prices["ethereum"]["usd"]
    except Exception as e:
        await update.message.reply_text("Fehler beim Abrufen der Preise.")
        return

    # GPT-Antwort holen
    prompt = (
        "Gibt es neue Nachrichten zu XRP oder Ripple? "
        "Nur relevante Entwicklungen der letzten 12–24 Stunden. "
        "Wenn nichts Relevantes, antworte exakt: 'Keine relevanten Updates.'"
    )

    try:
        response = await client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "Du bist ein sachlicher Nachrichten-Assistent."},
                {"role": "user", "content": prompt}
            ],
            temperature=0.3,
            max_tokens=400,
        )
        update_text = response.choices[0].message.content.strip()
    except Exception as e:
        await update.message.reply_text("Fehler beim Abrufen der News.")
        return

    # Antwort zusammenbauen
    text = (
        f"📢 *Ripple & XRP Update – {now}*\n\n"
        f"- *Kurs:* XRP bei {preis_xrp} USD\n"
        f"- *News:* {update_text}\n\n"
        f"🪙 *Weitere Kurse:*\n"
        f"- HBAR: {preis_hbar} USD\n"
        f"- SOL: {preis_sol} USD\n"
        f"- BTC: {preis_btc} USD\n"
        f"- ETH: {preis_eth} USD"
    )

    await update.message.reply_text(text, parse_mode="Markdown")

# === Tageszusammenfassungen ===
def init_scheduler(app):
    scheduler = AsyncIOScheduler(timezone="Europe/Berlin")

    for hour in [8, 14, 20]:
        scheduler.add_job(
            ripple_sec_news_check,
            CronTrigger(hour=hour, minute=0),
            name=f"Ripple SEC News {hour}h"
        )

    #scheduler.start()
    async def send_morning_summary():
        tz = pytz.timezone("Europe/Berlin")
        now = datetime.datetime.now(tz)
        start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)

        try:
            events = get_calendar_events(start, end)

            if events:
                grouped = {}
                for e in events:
                    cal = e.get("calendar", "Unbekannt")
                    grouped.setdefault(cal, []).append(e)

                text = f"Guten Morgen! Deine Termine heute ({start.strftime('%A, %d.%m.%Y')}):\n"
                for cal_name, evts in grouped.items():
                    text += f"\n📅 {cal_name}:\n"
                    for e in evts:
                        start_str = e['start'][11:16] if 'T' in e['start'] else ''
                        end_str = e['end'][11:16] if 'T' in e['end'] else ''
                        zeit = f"{start_str}-{end_str}" if start_str and end_str else "(ganztägig)"
                        text += f"- {zeit} {e['summary']}\n"
            else:
                text = "Guten Morgen! Heute stehen keine Termine im Kalender."

        except Exception as e:
            text = f"❌ Fehler beim Laden des Kalenders:\n{e}"

        # Aufgaben
        today = now.date()
        tasks = get_relevant_tasks(today)
        if tasks:
            text += "\n\n📝 Aufgaben heute:\n" + "\n".join(f"- {t}" for t in tasks)
        else:
            text += "\n\n📝 Heute stehen keine Aufgaben an."

        # Mailstatus prüfen
        mail_summary, open_mails = await check_mail_status()
        if mail_summary:
            text += "\n\n" + mail_summary
        if open_mails:
            await create_mail_check_task(open_mails)

        # Nachricht senden
        await app.bot.send_message(chat_id=CHAT_ID, text=text)

    async def send_evening_summary():
        tz = pytz.timezone("Europe/Berlin")
        now = datetime.datetime.now(tz)
        start = (now + datetime.timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
        end = start + datetime.timedelta(days=1)

        events = get_calendar_events(start, end)
        if events:
            grouped = {}
            for e in events:
                cal = e.get("calendar", "Unbekannt")
                grouped.setdefault(cal, []).append(e)

            text = f"🌙 Vorschau auf morgen ({start.strftime('%A, %d.%m.%Y')}):\n"
            for cal_name, evts in grouped.items():
                text += f"\n📘 {cal_name}:\n"
                for e in evts:
                    start_str = e['start'][11:16] if 'T' in e['start'] else ''
                    end_str = e['end'][11:16] if 'T' in e['end'] else ''
                    zeit = f"{start_str}-{end_str}" if start_str and end_str else "(ganztägig)"
                    text += f"- {zeit} {e['summary']}\n"
        else:
            text = "🌙 Morgen stehen keine Termine im Kalender."

        tomorrow = (now + datetime.timedelta(days=1)).date()
        tasks = get_relevant_tasks(tomorrow)
        if tasks:
            text += "\n\n📝 Aufgaben morgen:\n" + "\n".join(f"- {t}" for t in tasks)
        else:
            text += "\n\n📝 Morgen stehen keine Aufgaben an."

        await app.bot.send_message(chat_id=CHAT_ID, text=text)

    # Scheduler-Jobs
    scheduler.add_job(send_morning_summary, trigger="cron", hour=6, minute=30)
    scheduler.add_job(send_morning_summary, trigger="cron", hour=7, minute=30)
    scheduler.add_job(send_morning_summary, trigger="cron", hour=10, minute=0)
    scheduler.add_job(send_morning_summary, trigger="cron", hour=15, minute=0)
    scheduler.add_job(send_evening_summary, trigger="cron", hour=21, minute=0)
    scheduler.start()

async def mail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    summary, open_mails = await check_mail_status()
    if summary:
        await update.message.reply_text(summary)
    else:
        await update.message.reply_text("📭 Keine unbeantworteten Mails gefunden.")

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
    app.add_handler(CommandHandler("mail", mail_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, global_frage))
    app.add_handler(CommandHandler("xrp", xrp_command))

    init_scheduler(app)

    await app.initialize()
    await app.start()
    await app.updater.start_polling()
    print("✅ Polling gestartet.")
    print("✅ Bot läuft auf Fly.io.")
    await asyncio.Event().wait()

if __name__ == "__main__":
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

    loop.run_until_complete(setup_application())
