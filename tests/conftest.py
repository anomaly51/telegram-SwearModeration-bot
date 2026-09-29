import os


# Unit tests must never read credentials or connect to the developer's real database.
os.environ.update(
    DB_HOST="127.0.0.1",
    DB_PORT="1",
    DB_USER="test",
    DB_PASS="test",
    DB_NAME="test",
    DATABASE_URL="postgresql+asyncpg://test:test@127.0.0.1:1/test",
    BOT_TOKEN="123456:TEST",
    ADMIN_ID="1",
    SENTRY_DSN="",
)
