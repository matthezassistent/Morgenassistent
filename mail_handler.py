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


def list_threads(query: str, strict: bool = False) -> List[str]:
    if not strict:
        if "category:primary" not in query:
            query += " category:primary"
        if "-from:noreply" not in query:
            query += " -from:noreply -from:no-reply"
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
    headers = last_msg.get("payload", {}).get("headers", [])
    from_header = next((h["value"] for h in headers if h["name"].lower() == "from"), "")
    snippet = last_msg.get("snippet", "")

    question_keywords = [
        "?", "kannst du", "würden sie", "bitte", "könntest du", "was ist", "wann", "wie", "wo", "warum", "soll ich",
        "can you", "could you", "please", "would you", "what is", "when", "how", "where", "why", "should I",
        "kun je", "zou je", "alsjeblieft", "wat is", "wanneer", "hoe", "waar", "waarom", "moet ik"
    ]

    snippet_lower = snippet.lower()
    from_header_lower = from_header.lower()

    newsletter_phrases = [
        "to unsubscribe", "google calendar", "event update", "termin wurde aktualisiert", "calendar invitation", "automated message", "you are receiving this", "no reply needed",
        "nicht antworten", "automatisch generiert", "du erhältst diese nachricht", "abmelden", "gitpod",
        "keine antwort erforderlich", "benachrichtigungseinstellungen", "email-einstellungen",
        "ihre email wurde hinterlegt", "sie erhalten diese e-mail", "rufen sie das portal auf",
        "please do not reply to this email", "chess.com customer support", "update your notification settings",
        "this email was sent to", "download on the app store", "get it on google play",
        "Game over", "passwort reset", "aktualisierte einladung", "bestätige deine transaktion", "termin abgesagt",
        "einladung", "livestream", "transaction", "support", "kundenservice",
        "dies ist keine antwortadresse", "kalendereinladung", "meeting invitation"
    ]
    for phrase in newsletter_phrases:
        if phrase in snippet_lower:
            print(f"🛑 Gefiltert durch Stichwort '{phrase}' im Snippet: {snippet_lower[:100]}")
            return False

    if any(service in from_header_lower for service in ["calendar", "google", "no-reply", "noreply", "donotreply"]):
        print(f"🛑 Gefiltert durch Absender '{from_header_lower}'")
        return False

    is_sent_by_me = "SENT" in last_msg.get("labelIds", [])
    contains_question = any(kw in snippet_lower for kw in question_keywords)

    if not is_sent_by_me:
        return contains_question

    if is_sent_by_me:
        if len(messages) > 1 and messages[-1] == messages[-1]:
            return contains_question

    return False

def archive_old_emails():
    old_threads = list_threads("older_than:7d label:inbox", strict=True)
    for thread_id in old_threads:
        try:
            gmail.users().threads().modify(userId="me", id=thread_id, body={"removeLabelIds": ["INBOX"]}).execute()
        except Exception as e:
            print(f"⚠️ Fehler beim Archivieren von Thread {thread_id}: {e}")

async def check_mail_status() -> Tuple[str, List[dict]]:
    archive_old_emails()
    recent_threads = list_threads("newer_than:3d category:primary -from:noreply -from:no-reply")
    incoming_mails = []
    outgoing_mails = []
    summary = ""

    for thread_id in recent_threads:
        messages = get_thread_messages(thread_id)
        if not messages:
            continue

        last_msg = messages[-1]
        subject = extract_subject(last_msg)[:60]
        link = extract_snippet_link(last_msg["id"])

        if is_unanswered(messages):
            if "SENT" in last_msg.get("labelIds", []):
                outgoing_mails.append({"subject": subject, "link": link})
            else:
                incoming_mails.append({"subject": subject, "link": link})

    if incoming_mails or outgoing_mails:
        summary = "📬 Es gibt unbeantwortete Mails:\n\n"

        if incoming_mails:
            summary += "📥 Eingehende Mails ohne Antwort:\n"
            for mail in incoming_mails:
                summary += f"- {mail['subject']}\n🔗 {mail['link']}\n"
            summary += "\n"

        if outgoing_mails:
            summary += "📤 Gesendete Mails ohne Rückmeldung:\n"
            for mail in outgoing_mails:
                summary += f"- {mail['subject']}\n🔗 {mail['link']}\n"

    return summary, incoming_mails + outgoing_mails


async def create_mail_check_task(open_mails: List[dict]):
    if not open_mails:
        return

    content = "📬 Es gibt unbeantwortete E-Mails, bitte prüfen."
    due_date = datetime.date.today().isoformat()
    #todoist.add_task(content=content, due_date=due_date, priority=3)
