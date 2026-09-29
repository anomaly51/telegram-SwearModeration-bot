import asyncio
import getpass
import shutil
import socket
import subprocess
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import URL, func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from database import orm_query, report_query
from database.models import Base, DailyMessages, ProcessedMessage, SwearLog
from database.orm_query import TZ_KYIV, BadWordsRepository, RepositoryError


@pytest.fixture(scope="module")
def postgres_url():
    """Start an isolated cluster; never use .env, DATABASE_URL or an existing server."""
    initdb = shutil.which("initdb")
    if not initdb:
        candidates = sorted(Path("/usr/lib/postgresql").glob("*/bin/initdb"))
        initdb = str(candidates[-1]) if candidates else None
    if not initdb:
        pytest.skip("Install PostgreSQL server binaries to run integration tests")
    pg_ctl = str(Path(initdb).with_name("pg_ctl"))
    with tempfile.TemporaryDirectory(prefix="swear-test-") as directory:
        data = str(Path(directory) / "data")
        subprocess.run(
            [initdb, "-D", data, "-A", "trust", "--no-locale"], check=True, capture_output=True
        )
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            port = sock.getsockname()[1]
        subprocess.run(
            [
                pg_ctl,
                "-D",
                data,
                "-l",
                str(Path(directory) / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {port} -k {directory}",
                "-w",
                "start",
            ],
            check=True,
            capture_output=True,
        )
        try:
            yield URL.create(
                "postgresql+asyncpg",
                username=getpass.getuser(),
                host="127.0.0.1",
                port=port,
                database="postgres",
            )
        finally:
            subprocess.run(
                [pg_ctl, "-D", data, "-m", "fast", "-w", "stop"], check=True, capture_output=True
            )


@pytest.fixture
def database(postgres_url, monkeypatch):
    engine = create_async_engine(postgres_url, poolclass=NullPool)
    sessions = async_sessionmaker(engine, expire_on_commit=False)
    monkeypatch.setattr(orm_query, "async_session_maker", sessions)
    monkeypatch.setattr(report_query, "async_session_maker", sessions)

    async def setup():
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        await BadWordsRepository.ensure_daily_swears_integrity()

    asyncio.run(setup())
    yield sessions
    asyncio.run(engine.dispose())


def message_args(message_id=1, **changes):
    timestamp = datetime(2026, 9, 1, 23, 59, tzinfo=TZ_KYIV)
    return dict(
        chat_id=-1,
        message_id=message_id,
        user_id=1,
        username="Test",
        timestamp=timestamp,
        version=timestamp,
        swear_words=["сука"],
        neutral_words=[],
        **changes,
    )


def test_replay_concurrency_and_edits_preserve_totals(database):
    async def scenario():
        args = message_args()
        await asyncio.gather(*(BadWordsRepository.record_message(**args) for _ in range(8)))
        await asyncio.gather(
            *(BadWordsRepository.record_message(**message_args(message_id=i)) for i in range(2, 12))
        )
        assert await BadWordsRepository.get_swear_count(-1, 1, args["timestamp"].date()) == 11
        edit = {
            **args,
            "version": args["version"] + timedelta(days=1),
            "swear_words": [],
            "neutral_words": ["дурак"],
            "edited": True,
        }
        assert await BadWordsRepository.record_message(**edit)
        assert not await BadWordsRepository.record_message(**edit)
        assert not await BadWordsRepository.record_message(**args)
        assert await BadWordsRepository.get_swear_count(-1, 1, args["timestamp"].date()) == 10
        async with database() as session:
            assert await session.scalar(select(func.sum(DailyMessages.message_count))) == 11
            assert await session.scalar(select(func.count(SwearLog.id))) == 11
            log = await session.scalar(select(SwearLog).where(SwearLog.message_id == 1))
            assert log.category == "neutral"
            assert log.timestamp.astimezone(TZ_KYIV).date() == args["timestamp"].date()
        # An unseen legacy edit must not add its already-counted words a second time.
        assert not await BadWordsRepository.record_message(**{**edit, "message_id": 99})

    asyncio.run(scenario())


def test_same_second_edits_use_update_order(database):
    async def scenario():
        args = message_args()
        await BadWordsRepository.record_message(**args, update_id=10)
        edit = {**args, "edited": True, "swear_words": []}
        assert await BadWordsRepository.record_message(**edit, update_id=11)
        assert not await BadWordsRepository.record_message(**args, update_id=10)
        assert await BadWordsRepository.get_swear_count(-1, 1, args["timestamp"].date()) == 0

    asyncio.run(scenario())


def test_message_write_rolls_back_all_counters_on_failure(database):
    async def scenario():
        args = message_args()
        with pytest.raises(RepositoryError):
            await BadWordsRepository.record_message(**{**args, "swear_words": [None]})
        async with database() as session:
            assert await session.scalar(select(func.count(DailyMessages.id))) == 0
            assert await session.scalar(select(func.count(ProcessedMessage.message_id))) == 0
        assert await BadWordsRepository.record_message(**args)

    asyncio.run(scenario())


def test_cleanup_preserves_month_profile(database):
    async def scenario():
        now = datetime.now(TZ_KYIV)
        timestamp = now.replace(day=1, hour=12, minute=0, second=0)
        args = {**message_args(), "timestamp": timestamp, "version": timestamp}
        await BadWordsRepository.record_message(**args)
        old = timestamp - timedelta(days=150)
        await BadWordsRepository.record_message(
            **{
                **args,
                "message_id": 2,
                "timestamp": old,
                "version": old,
            }
        )
        await BadWordsRepository.clear_old_logs(days=7)
        profile = await BadWordsRepository.get_user_month_profile(-1, 1, now.year, now.month)
        assert profile.favorite_word == "сука"
        assert profile.favorite_count == profile.unique_swear_count == 1
        async with database() as session:
            assert await session.scalar(select(func.count(SwearLog.id))) == 1

    asyncio.run(scenario())


def test_report_recovery_after_failed_send_and_restart(database):
    import scheduler

    async def scenario():
        await BadWordsRepository.subscribe_chat(-1)
        await BadWordsRepository.record_message(**message_args())
        bot = AsyncMock()
        bot.send_message.side_effect = [RuntimeError("network"), None, None]
        now = datetime(2026, 10, 1, 0, 6, tzinfo=TZ_KYIV)
        await scheduler.send_scheduled_reports(bot, now)
        assert bot.send_message.await_count == 3
        # New client/scheduler, same DB: only the failed daily report is retried.
        restarted_bot = AsyncMock()
        await scheduler.send_scheduled_reports(restarted_bot, now)
        assert restarted_bot.send_message.await_count == 1
        await scheduler.send_scheduled_reports(restarted_bot, now)
        assert restarted_bot.send_message.await_count == 1

    asyncio.run(scenario())


def test_partial_report_resumes_at_unsent_chunk(database):
    from scheduler import deliver_report

    async def scenario():
        start = datetime(2026, 9, 1).date()
        row = await report_query.ReportRepository.prepare(-1, "monthly", start, ["one", "two"])
        bot = AsyncMock()
        bot.send_message.side_effect = [None, RuntimeError("network")]
        with pytest.raises(RuntimeError):
            await deliver_report(bot, row)
        pending = await report_query.ReportRepository.pending(-1)
        assert pending[0].next_chunk == 1
        bot = AsyncMock()
        await deliver_report(bot, pending[0])
        bot.send_message.assert_awaited_once_with(-1, "two")

    asyncio.run(scenario())


def test_unavailable_chat_does_not_block_other_subscribers(database):
    import scheduler

    async def scenario():
        await BadWordsRepository.subscribe_chat(-1)
        await BadWordsRepository.subscribe_chat(-2)
        sent = []

        async def send(chat_id, text):
            if chat_id == -1:
                raise RuntimeError("chat unavailable")
            sent.append((chat_id, text))

        bot = AsyncMock()
        bot.send_message.side_effect = send
        await scheduler.send_scheduled_reports(
            bot,
            datetime(2026, 10, 1, 0, 6, tzinfo=TZ_KYIV),
        )
        assert len(sent) == 3
        assert all(chat_id == -2 for chat_id, _ in sent)

    asyncio.run(scenario())


def test_week_and_month_use_correct_chat_and_date_boundaries(database):
    import scheduler

    async def scenario():
        for index, (chat_id, timestamp) in enumerate(
            [
                (-1, datetime(2026, 9, 20, 23, 59, tzinfo=TZ_KYIV)),
                (-1, datetime(2026, 9, 21, 0, 0, tzinfo=TZ_KYIV)),
                (-1, datetime(2026, 9, 27, 23, 59, tzinfo=TZ_KYIV)),
                (-1, datetime(2026, 9, 28, 0, 0, tzinfo=TZ_KYIV)),
                (-1, datetime(2026, 9, 30, 23, 59, tzinfo=TZ_KYIV)),
                (-1, datetime(2026, 10, 1, 0, 0, tzinfo=TZ_KYIV)),
                (-2, datetime(2026, 9, 22, 12, 0, tzinfo=TZ_KYIV)),
            ]
        ):
            await BadWordsRepository.record_message(
                **{
                    **message_args(index),
                    "chat_id": chat_id,
                    "timestamp": timestamp,
                    "version": timestamp,
                }
            )
        weekly = await scheduler.build_period_report(
            -1,
            "weekly",
            datetime(2026, 9, 21).date(),
            datetime(2026, 9, 28).date(),
        )
        monthly = await scheduler.build_period_report(
            -1,
            "monthly",
            datetime(2026, 9, 1).date(),
            datetime(2026, 10, 1).date(),
        )
        assert "Всего матов: 2" in weekly
        assert "Всего матов за месяц: 5" in monthly

    asyncio.run(scenario())


def test_concurrent_subscription_is_idempotent(database):
    async def scenario():
        results = await asyncio.gather(*(BadWordsRepository.subscribe_chat(-1) for _ in range(8)))
        assert sum(results) == 1
        assert await BadWordsRepository.get_all_active_chats() == [-1]

    asyncio.run(scenario())


def test_schema_upgrade_keeps_legacy_data(database):
    async def scenario():
        async with database() as session:
            await session.execute(text("ALTER TABLE swear_logs DROP COLUMN message_id"))
            await session.execute(
                text(
                    "INSERT INTO daily_swears "
                    "(chat_id,user_id,username,badwords_count,neutral_count,date) "
                    "VALUES (-1,1,'Test',12,3,'2026-09-01')"
                )
            )
            await session.commit()
        await BadWordsRepository.ensure_daily_swears_integrity()
        await BadWordsRepository.ensure_daily_swears_integrity()
        assert await BadWordsRepository.get_swear_count(-1, 1, datetime(2026, 9, 1).date()) == 12

    asyncio.run(scenario())


def test_only_one_process_can_own_bot_lock(database):
    from bot_runtime import AlreadyRunningError, single_instance

    async def scenario():
        engine = database.kw["bind"]
        async with single_instance(engine, 123):
            with pytest.raises(AlreadyRunningError):
                async with single_instance(engine, 123):
                    pytest.fail("Duplicate bot acquired the same lock")
            async with single_instance(engine, 456):
                pass
        async with single_instance(engine, 123):
            pass

    asyncio.run(scenario())
