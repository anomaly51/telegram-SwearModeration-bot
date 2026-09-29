import asyncio
from contextlib import asynccontextmanager
from time import time

from aiogram.client.session.middlewares.base import BaseRequestMiddleware
from aiogram.exceptions import TelegramConflictError
from aiogram.methods import GetUpdates
from loguru import logger
from sqlalchemy import text

from metrics import (
    INSTANCE_LOCK_HEALTHY,
    POLLING_LAST_CONFLICT,
    POLLING_LAST_SUCCESS,
    POLLING_STARTED,
)


class AlreadyRunningError(RuntimeError):
    pass


@asynccontextmanager
async def single_instance(engine, bot_id: int):
    """Hold a dedicated PostgreSQL session lock until polling and scheduling stop."""
    async with engine.connect() as connection:
        connection = await connection.execution_options(isolation_level="AUTOCOMMIT")
        acquired = await connection.scalar(
            text("SELECT pg_try_advisory_lock(hashtextextended(:key, 0))"),
            {"key": f"telegram-bot-instance:{bot_id}"},
        )
        if not acquired:
            raise AlreadyRunningError("Another instance already owns this bot's database lock")
        INSTANCE_LOCK_HEALTHY.set(1)
        try:
            yield connection
        finally:
            INSTANCE_LOCK_HEALTHY.set(0)
            # Discard the physical connection: a session lock must never return to the pool.
            await connection.invalidate()


async def monitor_lock(connection, interval: float = 5):
    while True:
        await asyncio.sleep(interval)
        try:
            async with asyncio.timeout(5):
                await connection.execute(text("SELECT 1"))
        except Exception:
            INSTANCE_LOCK_HEALTHY.set(0)
            raise


async def run_with_lock_monitor(operation, connection):
    """Stop polling immediately if its lock connection is lost."""
    worker = asyncio.create_task(operation)
    monitor = asyncio.create_task(monitor_lock(connection))
    try:
        done, _ = await asyncio.wait((worker, monitor), return_when=asyncio.FIRST_COMPLETED)
        for task in done:
            task.result()
    finally:
        for task in (worker, monitor):
            task.cancel()
        await asyncio.gather(worker, monitor, return_exceptions=True)


class PollingHealthMiddleware(BaseRequestMiddleware):
    def __init__(self):
        self.started = False

    async def __call__(self, make_request, bot, method):
        if not isinstance(method, GetUpdates):
            return await make_request(bot, method)
        if not self.started:
            POLLING_STARTED.set(time())
            self.started = True
        try:
            result = await make_request(bot, method)
        except TelegramConflictError:
            POLLING_LAST_CONFLICT.set(time())
            raise
        POLLING_LAST_SUCCESS.set(time())
        return result


async def wait_for_instance(engine, bot_id, operation):
    """A standby copy never calls Telegram or starts scheduled jobs."""
    while True:
        try:
            async with single_instance(engine, bot_id) as connection:
                await run_with_lock_monitor(operation(), connection)
                return
        except AlreadyRunningError:
            logger.warning("Другой экземпляр бота уже работает; ожидаю освобождения блокировки")
            await asyncio.sleep(30)
