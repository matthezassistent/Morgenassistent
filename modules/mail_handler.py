import datetime
import base64
import pickle
import os
from io import BytesIO
from typing import List, Tuple
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from todoist_api_python.api import TodoistAPI

# === ENV & SETUP ===
TOKEN_PKL_BASE64 = os.getenv("TOKEN_PKL_BASE64")
TODOIST_API_TOKEN = os.getenv("TODOIST_API_TOKEN")

if not TOKEN_PKL_BASE64:
    raise RuntimeError("TOKEN_PKL_BASE64 nicht gesetzt")

# === Load Gmail Credentials from token.pkl ===
creds = pickle.load(BytesIO(base64.b64decode(TOKEN_PKL_BASE64)))
gmail = build("gmail", "v1", credentials=creds)
todoist = TodoistAPI(TODOIST_API_TOKEN)


# === Hilfsfunktionen ===
def list_threads(query: str) -> List[str]:
    response = gmail.users().threads().list(userId='me', q=query).execute()
    return [t['id'] for t in response.get('threads', [])]

def get_thread_messages(thread_id: str):
    thread = gmail.users().threads().get(userId='me', id=thread_id, format='metadata').execute()
    return thread.get("messages", [])

def extract_subject(msg):
    for h in msg.get("payload", {}).get("headers", []):
        if h["name"] == "Subject":
            return h["value"]
    return "(Kein Betreff)"

def extract_snippet_link(msg_id: str) -> str:
    return f"https://mail.google.com/mail/u/0/#inbox/{msg_id}"

def is_unanswered(messages: List[dict]) -> bool:
    if not messages:
        return False
    last_msg = messages[-1]
    return not last_msg.get("labelIds") or "SENT" not in last_msg.get("labelIds", [])

def archive_old_emails():
    old_threads = list_threads("older_than:7d label:inbox")
    for thread_id in old_threads:
        try:
            gmail.users().threads().modify(userId="me", id=thread_id, body={"removeLabelIds": ["INBOX"]}).execute()
        except Exception as e:
            print(f"⚠️ Fehler beim Archivieren von Thread {thread_id}: {e}")


async def check_mail_status() -> Tuple[str, List[dict]]:
    archive_old_emails()

    # Finde Threads der letzten 7 Tage
    recent_threads = list_threads("newer_than:7d")
    open_mails = []
    summaries = []

    for thread_id in recent_threads:
        messages = get_thread_messages(thread_id)
        if is_unanswered(messages):
            subject = extract_subject(messages[-1])[:60]
            link = extract_snippet_link(messages[-1]["id"])
            open_mails.append({"subject": subject, "link": link})
            summaries.append(f"- {subject}\n🔗 {link}")

    if open_mails:
        summary = "📬 Es gibt unbeantwortete Mails:\n\n" + "\n".join(summaries)
    else:
        summary = ""

    return summary, open_mails


async def create_mail_check_task(open_mails: List[dict]):
    content = "📬 Offene Mails prüfen (letzte 7 Tage)\n\n"
    for mail in open_mails:
        content += f"– {mail['subject']}\n🔗 {mail['link']}\n"

    due_date = datetime.date.today().isoformat()
    await todoist.add_task(content=content, due_date=due_date, priority=3)
