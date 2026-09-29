import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramConflictError
from aiogram.methods import GetMe, GetUpdates

import bot_runtime
from healthcheck import polling_is_healthy
from logger_config import AlertCooldown


def test_conflict_alert_is_sent_once_per_cooldown():
    now = [100.0]
    limiter = AlertCooldown(seconds=900, clock=lambda: now[0])
    record = {"name": "aiogram", "function": "polling", "message": "TelegramConflictError"}
    assert limiter(record)
    for _ in range(30):
        now[0] += 10
        assert not limiter(record)
    now[0] = 1000
    assert limiter(record)
    assert limiter({**record, "message": "Database unavailable"})


def test_alert_limiter_memory_is_bounded():
    limiter = AlertCooldown(max_keys=3)
    for i in range(10):
        limiter({"name": "test", "function": "test", "message": str(i)})
    assert len(limiter.sent) == 3


@pytest.mark.parametrize(
    "success,conflict,lock,expected",
    [
        (0, 0, 1, False),
        (990, 0, 1, True),
        (990, 980, 1, False),
        (990, 900, 1, True),
        (800, 0, 1, False),
        (990, 0, 0, False),
    ],
)
def test_readiness_requires_actual_healthy_polling(success, conflict, lock, expected):
    metrics = (
        f"bot_polling_last_success_timestamp {success}\n"
        f"bot_polling_last_conflict_timestamp {conflict}\n"
        f"bot_instance_lock_healthy {lock}\n"
        "bot_polling_started_timestamp 900\n"
    )
    assert polling_is_healthy(metrics, now=1000) is expected


def test_deployment_does_not_pass_before_observation_window():
    metrics = (
        "bot_instance_lock_healthy 1\n"
        "bot_polling_started_timestamp 990\n"
        "bot_polling_last_success_timestamp 995\n"
        "bot_polling_last_conflict_timestamp 0\n"
    )
    assert not polling_is_healthy(metrics, now=1000)


def test_request_middleware_tracks_only_polling(monkeypatch):
    success = Mock()
    conflict = Mock()
    monkeypatch.setattr(bot_runtime, "POLLING_LAST_SUCCESS", success)
    monkeypatch.setattr(bot_runtime, "POLLING_LAST_CONFLICT", conflict)

    async def scenario():
        middleware = bot_runtime.PollingHealthMiddleware()
        bot = SimpleNamespace()
        await middleware(AsyncMock(return_value=True), bot, GetMe())
        success.set.assert_not_called()
        await middleware(AsyncMock(return_value=[]), bot, GetUpdates())
        success.set.assert_called_once()
        method = GetUpdates()
        failing = AsyncMock(side_effect=TelegramConflictError(method, "competing poller"))
        with pytest.raises(TelegramConflictError):
            await middleware(failing, bot, method)
        conflict.set.assert_called_once()
        assert success.set.call_count == 1

    asyncio.run(scenario())


def test_loss_of_database_lock_cancels_bot(monkeypatch):
    stopped = []

    async def operation():
        try:
            await asyncio.Event().wait()
        finally:
            stopped.append(True)

    async def failed_monitor(connection):
        await asyncio.sleep(0)
        raise ConnectionError("database disconnected")

    monkeypatch.setattr(bot_runtime, "monitor_lock", failed_monitor)
    with pytest.raises(ConnectionError):
        asyncio.run(bot_runtime.run_with_lock_monitor(operation(), Mock()))
    assert stopped == [True]
