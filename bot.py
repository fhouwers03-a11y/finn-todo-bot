import os
import asyncio
import logging
from datetime import datetime
import httpx
from telegram import Bot
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from telegram import Update
import anthropic
from apscheduler.schedulers.asyncio import AsyncIOScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN")
CHAT_ID = int(os.environ.get("CHAT_ID"))
ANTHROPIC_API_KEY = os.environ.get("ANTHROPIC_API_KEY")
FATHOM_API_KEY = os.environ.get("FATHOM_API_KEY")

anthropic_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

async def get_todays_meetings():
    """Fetch today's meetings from Fathom API"""
    today = datetime.now().strftime("%Y-%m-%d")
    headers = {"Authorization": f"Bearer {FATHOM_API_KEY}"}
    
    async with httpx.AsyncClient() as client:
        response = await client.get(
            "https://api.fathom.ai/v1/calls",
            headers=headers,
            params={"start_date": today, "end_date": today}
        )
        if response.status_code == 200:
            return response.json()
        else:
            logger.error(f"Fathom API error: {response.status_code} {response.text}")
            return None

async def get_meeting_summary(recording_id):
    """Fetch summary for a specific meeting"""
    headers = {"Authorization": f"Bearer {FATHOM_API_KEY}"}
    async with httpx.AsyncClient() as client:
        response = await client.get(
            f"https://api.fathom.ai/v1/calls/{recording_id}/summary",
            headers=headers
        )
        if response.status_code == 200:
            return response.json()
        return None

async def generate_todo_list(meetings_data):
    """Use Claude to extract Finn's action items from meetings"""
    if not meetings_data:
        return "Geen calls gevonden voor vandaag."
    
    meetings_text = str(meetings_data)
    
    message = anthropic_client.messages.create(
        model="claude-sonnet-4-20250514",
        max_tokens=1000,
        messages=[
            {
                "role": "user",
                "content": f"""Je bent een assistent die actiepunten filtert voor Finn Houwers uit meeting samenvattingen.

Hieronder zijn de meetings van vandaag. Filter alle actiepunten die specifiek voor Finn zijn.
Geef een beknopte, duidelijke to-do lijst terug in het Nederlands.
Gebruik emoji's voor leesbaarheid.

Meeting data:
{meetings_text}

Geef alleen de to-do's voor Finn terug, geen andere informatie."""
            }
        ]
    )
    
    return message.content[0].text

async def send_daily_todo(bot: Bot):
    """Main function to fetch meetings and send todo list"""
    logger.info("Fetching today's meetings...")
    
    try:
        meetings = await get_todays_meetings()
        todo_list = await generate_todo_list(meetings)
        
        date_str = datetime.now().strftime("%d %B %Y")
        message = f"🌅 *Goedemorgen Finn!*\n\n📋 *Jouw to-do lijst voor {date_str}:*\n\n{todo_list}"
        
        await bot.send_message(
            chat_id=CHAT_ID,
            text=message,
            parse_mode="Markdown"
        )
        logger.info("Daily todo sent successfully!")
        
    except Exception as e:
        logger.error(f"Error sending daily todo: {e}")
        await bot.send_message(
            chat_id=CHAT_ID,
            text=f"⚠️ Er ging iets mis bij het ophalen van je to-do lijst: {str(e)}"
        )

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "👋 Hey Finn! Ik ben je dagelijkse to-do bot.\n\n"
        "Elke ochtend om 08:30 stuur ik je automatisch je actiepunten uit je Fathom calls.\n\n"
        "Commando's:\n"
        "/todo - Stuur me nu meteen je to-do lijst\n"
        "/start - Dit bericht"
    )

async def todo_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("⏳ Even je calls ophalen...")
    bot = context.bot
    await send_daily_todo(bot)

def main():
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start_command))
    application.add_handler(CommandHandler("todo", todo_command))
    
    scheduler = AsyncIOScheduler(timezone="Europe/Amsterdam")
    scheduler.add_job(
        lambda: asyncio.create_task(send_daily_todo(application.bot)),
        "cron",
        hour=8,
        minute=30
    )
    
    async def start_scheduler(app):
        scheduler.start()
        logger.info("Scheduler started - daily todo at 08:30 Amsterdam time")
    
    async def stop_scheduler(app):
        scheduler.shutdown()
    
    application.post_init = start_scheduler
    application.post_shutdown = stop_scheduler
    
    logger.info("Bot starting...")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == "__main__":
    main()
