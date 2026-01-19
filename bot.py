#!/usr/bin/env python3
"""
Main bot entry point.
Religious Q&A Telegram bot with semantic search.
"""

import asyncio
import logging
import sys

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.fsm.storage.memory import MemoryStorage

from config import config
from database import init_db, async_session
from services.search_engine import search_engine
from services.tag_service import TagService
from handlers import common_router, user_router, admin_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


async def on_startup(bot: Bot):
    """Startup tasks"""
    logger.info("Starting bot...")

    # Initialize database
    logger.info("Initializing database...")
    await init_db()

    # Initialize default tags
    logger.info("Initializing default tags...")
    async with async_session() as session:
        await TagService.init_default_tags(session)

    # Initialize search engine
    logger.info("Initializing search engine...")
    await search_engine.initialize()
    logger.info(f"Search engine ready. Documents indexed: {search_engine.get_document_count()}")

    logger.info("Bot started successfully!")


async def on_shutdown(bot: Bot):
    """Shutdown tasks"""
    logger.info("Shutting down bot...")


async def main():
    """Main function"""
    # Validate config
    if not config.BOT_TOKEN:
        logger.error("BOT_TOKEN is not set in .env file!")
        sys.exit(1)

    # Create bot instance
    bot = Bot(
        token=config.BOT_TOKEN,
        default=DefaultBotProperties(parse_mode=None)
    )

    # Create dispatcher with memory storage
    # For production with multiple workers, use Redis storage instead
    storage = MemoryStorage()
    dp = Dispatcher(storage=storage)

    # Register startup/shutdown handlers
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    # Register routers
    dp.include_router(common_router)
    dp.include_router(user_router)
    dp.include_router(admin_router)

    # Start polling
    logger.info("Starting polling...")
    try:
        await dp.start_polling(bot, allowed_updates=dp.resolve_used_update_types())
    finally:
        await bot.session.close()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Bot stopped by user")
