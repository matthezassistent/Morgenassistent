from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import ContextTypes
from email_tracker import check_emails_for_response, archive_email, defer_email

# === Nachrichtenvorlage ===
def format_email_message(email):
    subject = email['subject']
    sender = email['from']
    link = email['link']
    message = f"*{sender}*\n_{subject}_\n[Öffnen]({link})"
    return message

# === Buttons erstellen ===
def generate_buttons(email_id):
    return InlineKeyboardMarkup([
        [
            InlineKeyboardButton("✉️ Antworten", url=f"https://mail.google.com/mail/u/0/#inbox/{email_id}"),
            InlineKeyboardButton("⏰ Später", callback_data=f"defer:{email_id}"),
            InlineKeyboardButton("✅ Archivieren", callback_data=f"archive:{email_id}")
        ]
    ])

# === /mail-Befehl ===
async def mail_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    emails = check_emails_for_response()
    if not emails:
        await update.message.reply_text("Du hast derzeit keine unbeantworteten Mails.")
        return

    for email in emails:
        text = format_email_message(email)
        keyboard = generate_buttons(email['id'])
        await update.message.reply_markdown(text, reply_markup=keyboard)

# === Callback-Handler für Buttons ===
async def mail_callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()

    action, msg_id = query.data.split(":", 1)

    if action == "archive":
        archive_email(msg_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("✅ Archiviert.")

    elif action == "defer":
        defer_email(msg_id)
        await query.edit_message_reply_markup(reply_markup=None)
        await query.edit_message_text("⏰ Erinnerung um 6 Stunden verschoben.")
