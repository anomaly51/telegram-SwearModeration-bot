import asyncio
from datetime import datetime
from os import getenv
from zoneinfo import ZoneInfo

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from dotenv import load_dotenv
from loguru import logger
from prometheus_client import start_http_server
from sqlalchemy import text

from bot_runtime import PollingHealthMiddleware, wait_for_instance
from database.db import engine
from database.models import Base
from database.orm_query import BadWordsRepository
from handlers.user_handler import router
from logger_config import setup_logging
from metrics import ACTIVE_SUBSCRIPTIONS
from scheduler import send_scheduled_reports


load_dotenv()
TOKEN = getenv("BOT_TOKEN")

setup_logging()

if not TOKEN:
    logger.error("❌ BOT_TOKEN не найден в .env!")
    raise ValueError("BOT_TOKEN must be set")

ALLOWED_UPDATES = [
    "message",
    "edited_message",
    "channel_post",
    "edited_channel_post",
    "callback_query",
    "inline_query",
    "chosen_inline_result",
    "shipping_query",
    "pre_checkout_query",
    "poll",
    "poll_answer",
    "my_chat_member",
    "chat_member",
    "chat_join_request",
]

bot = Bot(token=TOKEN)

dp = Dispatcher(storage=MemoryStorage())

dp.include_router(router)


async def on_startup(bot):
    run_param = False

    logger.info("🚀 Инициализация базы данных...")
    try:
        if run_param:
            logger.warning("⚠️ Пересоздание базы данных...")
            async with engine.begin() as conn:
                await conn.run_sync(Base.metadata.drop_all)
            logger.info("✓ База данных очищена")

        async with engine.begin() as conn:
            await conn.execute(text("SET LOCAL lock_timeout = '2s'"))
            await conn.run_sync(Base.metadata.create_all)
        await BadWordsRepository.ensure_daily_swears_integrity()

        active_chats = await BadWordsRepository.get_all_active_chats()
        for chat_id in active_chats:
            try:
                chat = await bot.get_chat(chat_id)
                await BadWordsRepository.upsert_bot_chat(
                    chat_id=chat.id,
                    title=chat.title,
                    chat_type=chat.type,
                )
            except Exception:
                logger.exception(f"Не удалось обновить данные чата {chat_id}")

        ACTIVE_SUBSCRIPTIONS.set(len(active_chats))
        logger.info(f"🔄 Метрика подписок инициализирована: {len(active_chats)}")

        logger.info("✓ База данных инициализирована успешно")
    except Exception as e:
        logger.error(f"❌ Ошибка инициализации базы данных: {e}")
        raise


async def on_shutdown(bot):
    logger.info("⛔ Бот завершает работу")


async def main() -> None:
    bot.session.middleware(PollingHealthMiddleware())
    try:
        await wait_for_instance(engine, bot.id, run_bot)
    finally:
        await bot.session.close()
        await engine.dispose()


async def run_bot() -> None:
    logger.info("📱 Запуск бота...")
    await bot.delete_webhook(drop_pending_updates=False)
    dp.startup.register(on_startup)
    dp.shutdown.register(on_shutdown)

    scheduler = AsyncIOScheduler(timezone=ZoneInfo("Europe/Kyiv"))

    async def start_scheduler(bot):
        scheduler.add_job(
            send_scheduled_reports,
            "interval",
            minutes=5,
            args=[bot],
            next_run_time=datetime.now(ZoneInfo("Europe/Kyiv")),
            coalesce=True,
            max_instances=1,
            misfire_grace_time=300,
        )
        scheduler.add_job(
            BadWordsRepository.clear_old_logs,
            "cron",
            hour=3,
            minute=0,
            args=[90],
        )
        scheduler.start()

    dp.startup.register(start_scheduler)
    try:
        start_http_server(8000)
        await dp.start_polling(bot, allowed_updates=ALLOWED_UPDATES)
    finally:
        if scheduler.running:
            scheduler.shutdown(wait=False)


if __name__ == "__main__":
    logger.info("🔧 Инициализация приложения...")
    asyncio.run(main())
