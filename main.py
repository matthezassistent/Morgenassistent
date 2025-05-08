import os
import asyncio
from telegram import Update, Bot
from telegram.ext import (
    Application, CommandHandler, ContextTypes
)

# Umgebungsvariablen laden
BOT_TOKEN = os.getenv("BOT_TOKEN")
CHAT_ID = int(os.getenv("CHAT_ID", "8011259706"))

print("🚀 Starte minimalen Bot...")
print("BOT_TOKEN:", BOT_TOKEN[:8] if BOT_TOKEN else "❌ NICHT GESETZT")

# Handler für /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    print("📥 /start empfangen von:", update.effective_user.username)
    await update.message.reply_text("👋 Hallo! Ich bin dein Assistent (minimal).")

# Anwendung initialisieren
async def setup_application() -> Application:
    print("🔧 setup_application gestartet")
    app = Application.builder().token(BOT_TOKEN).build()
    await app.bot.delete_webhook(drop_pending_updates=True)
    app.add_handler(CommandHandler("start", start))
    print("✅ /start-Handler registriert")
    return app

# Start-Logik für Render (kein asyncio.run!)
if __name__ == "__main__":
    loop = asyncio.get_event_loop()

    async def main():
        print("✅ Bot wird gestartet...")
        app = await setup_application()
        print("✅ Application aufgebaut")
        await app.initialize()
        print("✅ Initialisiert")
        await app.start()
        print("✅ Gestartet – warte jetzt dauerhaft")
        await asyncio.Event().wait()

    loop.create_task(main())
    loop.run_forever()
