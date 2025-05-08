import os
import json
import base64
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from datetime import datetime, timedelta
from email.utils import parsedate_to_datetime

# === Einstellungen ===
LABEL_FILTER = "label:Allgemein in:inbox newer_than:30d"
ARCHIVE_FILE = "archived_emails.json"
DEFER_FILE = "deferred_emails.json"
IGNORED_SENDERS = [
    "noreply@", "newsletter@", "no-reply@", "automail@", "support@",
    "notifications@", "info@", "donotreply@", "google.com", "facebook.com", "zoom.us"
]
KEYWORDS_EXPECTING_ANSWER = [
    # Deutsch
    "kannst du", "könntest du", "würdest du", "wäre gut", "bitte", "brauch",
    "brauchst du", "schickst du", "gib mir", "meld dich", "lass uns wissen",
    "teile mir mit", "wollen wir", "sollen wir", "soll ich", "hättest du",
    "ist das möglich", "klären wir", "passt dir", "wann passt", "wie sieht es aus",
    "was meinst du", "geht das", "wir bräuchten", "ich würde dich bitten",
    "wäre das möglich", "bitte um info", "rückmeldung", "deine meinung",
    # Englisch
    "can you", "could you", "would you", "should we", "let me know",
    "please", "i need", "would be great", "i’d like", "send me", "is it possible",
    "get back to me", "respond", "follow up", "any update", "what do you think",
    "are you available", "do you have time", "your input", "your opinion",
    "i’d appreciate", "we need", "looking forward to your reply", "i hope to hear"
]

# === Hilfsfunktionen ===
def load_json_file(path):
    if os.path.exists(path):
        with open(path, "r") as f:
            return json.load(f)
    return []

def save_json_file(path, data):
    with open(path, "w") as f:
        json.dump(data, f)

def get_gmail_service():
    creds = Credentials.from_authorized_user_file("token.json", [
        'https://www.googleapis.com/auth/gmail.modify'])
    return build('gmail', 'v1', credentials=creds)

def extract_text(payload):
    if 'parts' in payload:
        for part in payload['parts']:
            if part['mimeType'] == 'text/plain':
                data = part['body'].get('data')
                if data:
                    return base64.urlsafe_b64decode(data).decode("utf-8")
    return ""

def message_needs_reply(sender, snippet, body):
    sender = sender.lower()
    if any(x in sender for x in IGNORED_SENDERS):
        return False
    if '?' in snippet or '?' in body:
        return True
    body_lower = body.lower()
    return any(keyword in body_lower for keyword in KEYWORDS_EXPECTING_ANSWER)

def is_deferred(msg_id):
    deferred = load_json_file(DEFER_FILE)
    for entry in deferred:
        if entry['id'] == msg_id:
            if datetime.now() < datetime.fromisoformat(entry['defer_until']):
                return True
    return False

def check_emails_for_response():
    archived = load_json_file(ARCHIVE_FILE)
    service = get_gmail_service()
    results = service.users().messages().list(userId='me', q=LABEL_FILTER, maxResults=30).execute()
    messages = results.get('messages', [])
    reply_needed = []

    for msg in messages:
        msg_id = msg['id']
        if msg_id in archived or is_deferred(msg_id):
            continue

        msg_data = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        headers = {h['name']: h['value'] for h in msg_data['payload']['headers']}
        sender = headers.get('From', '')
        subject = headers.get('Subject', '(kein Betreff)')
        date = headers.get('Date', '')
        snippet = msg_data.get('snippet', '')
        body = extract_text(msg_data['payload'])

        if message_needs_reply(sender, snippet, body):
            thread_id = msg_data.get('threadId')
            gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"
            reply_needed.append({
                'id': msg_id,
                'from': sender,
                'subject': subject,
                'date': date,
                'link': gmail_link
            })

    # Ergänzung: gesendete Mails prüfen
    sent_results = service.users().messages().list(userId='me', q="label:sent label:Allgemein older_than:2d", maxResults=20).execute()
    sent_messages = sent_results.get('messages', [])

    for sent in sent_messages:
        msg_id = sent['id']
        if msg_id in archived or is_deferred(msg_id):
            continue

        sent_data = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
        headers = {h['name']: h['value'] for h in sent_data['payload']['headers']}
        subject = headers.get('Subject', '(kein Betreff)')
        date = headers.get('Date', '')
        snippet = sent_data.get('snippet', '')
        body = extract_text(sent_data['payload'])
        thread_id = sent_data.get('threadId')

        thread = service.users().threads().get(userId='me', id=thread_id, format='metadata').execute()
        messages_in_thread = thread.get('messages', [])
        after_sent = [m for m in messages_in_thread if m['id'] != msg_id and m['labelIds'] and 'SENT' not in m['labelIds']]

        if not after_sent and message_needs_reply("", snippet, body):
            gmail_link = f"https://mail.google.com/mail/u/0/#inbox/{thread_id}"
            reply_needed.append({
                'id': msg_id,
                'from': '(Du selbst)',
                'subject': subject,
                'date': date,
                'link': gmail_link
            })

    return reply_needed

def archive_email(message_id):
    archived = load_json_file(ARCHIVE_FILE)
    if message_id not in archived:
        service = get_gmail_service()
        service.users().messages().modify(
            userId='me',
            id=message_id,
            body={'removeLabelIds': ['INBOX']}
        ).execute()
        archived.append(message_id)
        save_json_file(ARCHIVE_FILE, archived)
        return True
    return False

def defer_email(message_id):
    deferred = load_json_file(DEFER_FILE)
    defer_until = (datetime.now() + timedelta(hours=6)).isoformat()
    deferred.append({"id": message_id, "defer_until": defer_until})
    save_json_file(DEFER_FILE, deferred)
    return True
