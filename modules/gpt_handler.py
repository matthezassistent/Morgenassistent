import os
from telegram import Update
from telegram.ext import CommandHandler, ContextTypes
from openai import OpenAI

openai_key = os.getenv("OPENAI_API_KEY")
client = OpenAI(api_key=openai_key)

async def frage(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not context.args:
        await update.message.reply_text("Bitte gib deine Frage ein, z. B. /frage Was ist BWV 1013?")
        return

    user_input = " ".join(context.args)
    try:
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[{"role": "user", "content": user_input}]
        )
        reply = response.choices[0].message.content.strip()
        await update.message.reply_text(reply[:4000])
    except Exception as e:
        await update.message.reply_text(f"Fehler bei GPT: {e}")

gpt_handlers = [
    CommandHandler("frage", frage)
]
