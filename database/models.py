from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import JSON, BigInteger, Date, DateTime, Integer, String, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class BadWords(Base):
    __tablename__ = "daily_swears"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "date", name="uq_daily_swears_chat_user_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    badwords_count: Mapped[int] = mapped_column(Integer, default=0)
    neutral_count: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[date] = mapped_column(Date)


class DailyMessages(Base):
    __tablename__ = "daily_messages"
    __table_args__ = (
        UniqueConstraint("chat_id", "user_id", "date", name="uq_daily_messages_chat_user_date"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    message_count: Mapped[int] = mapped_column(Integer, default=0)
    date: Mapped[date] = mapped_column(Date)


class MonthlyRareWordDiscovery(Base):
    __tablename__ = "monthly_rare_word_discoveries"
    __table_args__ = (
        UniqueConstraint(
            "chat_id",
            "year",
            "month",
            "word",
            name="uq_monthly_rare_word_discoveries_chat_year_month",
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    year: Mapped[int] = mapped_column(Integer)
    month: Mapped[int] = mapped_column(Integer)
    word: Mapped[str] = mapped_column(String(255))
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    discovered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(ZoneInfo("Europe/Kyiv"))
    )


class SwearLog(Base):
    __tablename__ = "swear_logs"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int | None] = mapped_column(BigInteger, nullable=True)
    username: Mapped[str] = mapped_column(String(255), nullable=True)
    word: Mapped[str] = mapped_column(String(255))
    category: Mapped[str] = mapped_column(String(32), default="swear")
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(ZoneInfo("Europe/Kyiv"))
    )


class ReportChat(Base):
    __tablename__ = "report_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)

    subscribed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(ZoneInfo("Europe/Kyiv"))
    )


class BotChat(Base):
    __tablename__ = "bot_chats"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=True)
    chat_type: Mapped[str] = mapped_column(String(32))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=lambda: datetime.now(ZoneInfo("Europe/Kyiv"))
    )


class ProcessedMessage(Base):
    """Latest counted version; stores word matches, never the original message text."""

    __tablename__ = "processed_messages"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    message_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger)
    date: Mapped[date] = mapped_column(Date)
    version: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    update_id: Mapped[int] = mapped_column(BigInteger, default=0)
    swear_words: Mapped[list[str]] = mapped_column(JSON)
    neutral_words: Mapped[list[str]] = mapped_column(JSON)


class ReportDelivery(Base):
    __tablename__ = "report_deliveries"

    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    kind: Mapped[str] = mapped_column(String(16), primary_key=True)
    period_start: Mapped[date] = mapped_column(Date, primary_key=True)
    chunks: Mapped[list[str]] = mapped_column(JSON)
    next_chunk: Mapped[int] = mapped_column(Integer, default=0)
