from database.db import Settings


def test_database_url_escapes_password_special_characters():
    settings = Settings(
        DB_HOST="db",
        DB_PORT=5432,
        DB_USER="user",
        DB_PASS="p@ss:word",
        DB_NAME="name",
        BOT_TOKEN="test-token",
        ADMIN_ID="1",
        DATABASE_URL=None,
    )

    assert settings.DATABASE_URL == ("postgresql+asyncpg://user:p%40ss%3Aword@db:5432/name")


def test_database_errors_are_not_empty_statistics(monkeypatch):
    import asyncio
    from datetime import date
    from unittest.mock import AsyncMock

    import pytest

    from database import orm_query

    session = AsyncMock()
    session.__aenter__.return_value = session
    session.execute.side_effect = RuntimeError("database unavailable")
    monkeypatch.setattr(orm_query, "async_session_maker", lambda: session)

    async def scenario():
        repo = orm_query.BadWordsRepository
        operations = [
            repo.get_swear_count(-1, 1, date(2026, 9, 1)),
            repo.get_all_for_date(-1, date(2026, 9, 1)),
            repo.subscribe_chat(-1),
            repo.unsubscribe_chat(-1),
            repo.get_user_month_profile(-1, 1, 2026, 9),
            repo.get_all_active_chats(),
        ]
        for operation in operations:
            with pytest.raises(orm_query.RepositoryError):
                await operation

    asyncio.run(scenario())
