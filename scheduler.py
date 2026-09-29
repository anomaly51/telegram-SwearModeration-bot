from datetime import date, datetime, timedelta
from types import SimpleNamespace

from aiogram.exceptions import TelegramRetryAfter
from loguru import logger

from database.orm_query import TZ_KYIV, BadWordsRepository, get_previous_month
from database.report_query import ReportRepository


MEDALS = ("🥇", "🥈", "🥉")
TELEGRAM_TEXT_LIMIT = 4096


def split_telegram_message(text: str, limit: int = TELEGRAM_TEXT_LIMIT) -> list[str]:
    if limit <= 0:
        raise ValueError("limit must be positive")
    if not text:
        return []

    chunks = []
    current_chars = []
    current_length = 0
    for char in text:
        char_length = 2 if ord(char) > 0xFFFF else 1
        if current_chars and current_length + char_length > limit:
            chunks.append("".join(current_chars))
            current_chars = []
            current_length = 0

        current_chars.append(char)
        current_length += char_length

    if current_chars:
        chunks.append("".join(current_chars))

    return chunks


async def _send_message(bot, chat_id: int, text: str) -> None:
    for chunk in split_telegram_message(text):
        await bot.send_message(chat_id, chunk)


def format_percent_delta(current: int, previous: int) -> str:
    if previous == 0:
        if current == 0:
            return "0%"
        return "новый месяц"

    delta = round((current - previous) / previous * 100)
    if delta > 0:
        return f"+{delta}%"
    if delta < 0:
        return f"{delta}%"
    return "0%"


def format_daily_report(records) -> str:
    ranked_records = sorted(
        (record for record in records if record.badwords_count > 0),
        key=lambda record: record.badwords_count,
        reverse=True,
    )
    total_swears = sum(record.badwords_count for record in records)
    total_neutral = sum(record.neutral_count for record in records)

    text_parts = ["🏆 Матный рейтинг дня\n\n"]
    if not ranked_records:
        text_parts.append("Сегодня матов не было.\n")

    for place, record in enumerate(ranked_records, start=1):
        medal = MEDALS[place - 1] if place <= len(MEDALS) else f"{place}."
        text_parts.append(
            f"{medal} {record.username or record.user_id} — {record.badwords_count}\n"
        )

    text_parts.append(
        f"\n━━━━━━━━━━━━━━━━\n"
        f"📊 Всего матов: {total_swears}\n"
        f"🟡 Нейтральных ругательств: {total_neutral}"
    )
    return "".join(text_parts)


def is_last_day_of_month(current_date: date) -> bool:
    return (current_date + timedelta(days=1)).month != current_date.month


def format_monthly_report(
    records,
    year: int,
    month: int,
    summary: SimpleNamespace | None = None,
    previous_summary: SimpleNamespace | None = None,
) -> str:
    ranked_records = sorted(
        (record for record in records if record.badwords_count > 0),
        key=lambda record: record.badwords_count,
        reverse=True,
    )
    total_swears = sum(record.badwords_count for record in records)
    total_neutral = sum(record.neutral_count for record in records)

    text_parts = [f"🏆 Матный рейтинг месяца {month:02d}.{year}\n\n"]
    if not ranked_records:
        text_parts.append("В этом месяце матов не было.\n")

    for place, record in enumerate(ranked_records, start=1):
        medal = MEDALS[place - 1] if place <= len(MEDALS) else f"{place}."
        text_parts.append(
            f"{medal} {record.username or record.user_id} — {record.badwords_count}\n"
        )

    text_parts.append(
        f"\n━━━━━━━━━━━━━━━━\n"
        f"📊 Всего матов за месяц: {total_swears}\n"
        f"🟡 Нейтральных ругательств за месяц: {total_neutral}"
    )

    if summary and previous_summary:
        delta = format_percent_delta(summary.swear_count, previous_summary.swear_count)
        text_parts.append(f"\n📈 К прошлому месяцу: {delta}")

        if summary.favorite_word:
            text_parts.append(f"\n❤️ Мат месяца: {summary.favorite_word}")

        if summary.max_day and summary.max_day_swears:
            text_parts.append(
                f"\n🔥 Самый матный день: "
                f"{summary.max_day.strftime('%d.%m')} — {summary.max_day_swears}"
            )

    return "".join(text_parts)


def format_weekly_report(records, start: date, end: date) -> str:
    text = format_daily_report(records)
    return text.replace(
        "🏆 Матный рейтинг дня",
        f"🏆 Матный рейтинг недели {start:%d.%m.%Y}–{end - timedelta(days=1):%d.%m.%Y}",
    ).replace("Сегодня матов не было.", "За неделю матов не было.")


def completed_periods(today: date) -> list[tuple[str, date, date]]:
    monday = today - timedelta(days=today.weekday())
    month_start = today.replace(day=1)
    previous_month = (month_start - timedelta(days=1)).replace(day=1)
    return [
        ("daily", today - timedelta(days=1), today),
        ("weekly", monday - timedelta(days=7), monday),
        ("monthly", previous_month, month_start),
    ]


async def build_period_report(chat_id: int, kind: str, start: date, end: date) -> str:
    records = await BadWordsRepository.get_all_for_period(chat_id, start, end)
    if kind == "daily":
        return (
            format_daily_report(records)
            .replace("Матный рейтинг дня", f"Матный рейтинг дня {start:%d.%m.%Y}")
            .replace("Сегодня матов не было.", "За этот день матов не было.")
        )
    if kind == "weekly":
        return format_weekly_report(records, start, end)
    prev_year, prev_month = get_previous_month(start.year, start.month)
    summary = await BadWordsRepository.get_chat_month_summary(chat_id, start.year, start.month)
    previous = await BadWordsRepository.get_chat_month_summary(chat_id, prev_year, prev_month)
    return format_monthly_report(records, start.year, start.month, summary, previous)


async def deliver_report(bot, delivery) -> None:
    for index in range(delivery.next_chunk, len(delivery.chunks)):
        await bot.send_message(delivery.chat_id, delivery.chunks[index])
        # Persist each successful part so retries resume a long report.
        await ReportRepository.advance(
            delivery.chat_id,
            delivery.kind,
            delivery.period_start,
            index + 1,
        )


async def send_scheduled_reports(bot, now: datetime | None = None):
    """Recover the latest closed periods and unfinished sends on every scheduler tick."""
    now = now or datetime.now(TZ_KYIV)
    today = (now.astimezone(TZ_KYIV) - timedelta(minutes=5)).date()
    try:
        active_chats = await BadWordsRepository.get_all_active_chats()
    except Exception:
        logger.exception("Не удалось получить подписки; повторим рассылку через 5 минут")
        return
    for chat_id in active_chats:
        try:
            pending = await ReportRepository.pending(chat_id)
        except Exception:
            logger.exception(f"Не удалось получить очередь отчетов чата {chat_id}")
            continue
        periods = completed_periods(today)
        tasks = [(row.kind, row.period_start, None, row) for row in pending]
        pending_keys = {(row.kind, row.period_start) for row in pending}
        tasks.extend(
            (kind, start, end, None)
            for kind, start, end in periods
            if (kind, start) not in pending_keys
        )
        for kind, start, end, delivery in tasks:
            try:
                delivery = delivery or await ReportRepository.get(chat_id, kind, start)
                if delivery is None:
                    report = await build_period_report(chat_id, kind, start, end)
                    delivery = await ReportRepository.prepare(
                        chat_id,
                        kind,
                        start,
                        split_telegram_message(report),
                    )
                await deliver_report(bot, delivery)
            except TelegramRetryAfter as e:
                logger.warning(f"Telegram ограничил рассылку на {e.retry_after} секунд")
                # Leave progress intact; the next tick retries instead of losing the report.
                return
            except Exception:
                logger.exception(f"Не удалось отправить {kind} отчет в чат {chat_id}")


# Compatibility for existing callers; all scheduled periods now share durable delivery.
send_daily_report = send_scheduled_reports
