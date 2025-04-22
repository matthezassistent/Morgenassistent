from telegram import Bot
import os

bot_token = os.getenv("BOT_TOKEN")  # aus Render-Umgebungsvariable
bot = Bot(token=bot_token)

bot.delete_webhook()
print("✅ Webhook gelöscht.")
