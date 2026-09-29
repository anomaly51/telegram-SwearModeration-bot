import html
from datetime import datetime, timedelta
from hashlib import sha256
from random import Random
from types import SimpleNamespace

from aiogram import F, Router
from aiogram.filters import Command, CommandStart
from aiogram.types import ErrorEvent, Message, Update
from loguru import logger

from database.db import settings
from database.orm_query import TZ_KYIV, BadWordsRepository, RepositoryError
from metrics import ACTIVE_SUBSCRIPTIONS, MESSAGES_TOTAL, SWEARS_TOTAL
from scheduler import format_monthly_report, format_weekly_report, split_telegram_message
from services import check_text_for_swears_detailed
from version_info import INSTANCE_NAME, PROCESS_STARTED_AT, RUNNING_BUILD, format_admin_build_report


router = Router()

MONTH_NAMES = {
    1: "Январь",
    2: "Февраль",
    3: "Март",
    4: "Апрель",
    5: "Май",
    6: "Июнь",
    7: "Июль",
    8: "Август",
    9: "Сентябрь",
    10: "Октябрь",
    11: "Ноябрь",
    12: "Декабрь",
}

RARE_FIND_WORDS = (
    "вафлер",
    "гнида",
    "говноед",
    "говнючка",
    "дрисня",
    "мандавошка",
    "мудозвон",
    "обсосок",
    "паскуда",
    "паскудник",
    "пердун",
    "ссанина",
    "шмара",
)
RARE_WORDS_PER_MONTH = 3


def parse_say_command(text: str | None) -> tuple[int | str | None, str]:
    parts = (text or "").split(maxsplit=2)
    if len(parts) < 3:
        return None, ""

    raw_chat_id = parts[1].strip()
    message_text = parts[2].strip()
    if not message_text:
        return None, ""

    if raw_chat_id.removeprefix("-").isascii() and raw_chat_id.removeprefix("-").isdigit():
        return int(raw_chat_id), message_text

    if raw_chat_id.startswith("@") and len(raw_chat_id) > 1:
        return raw_chat_id, message_text

    return None, ""


def format_log_word(word: str, category: str) -> str:
    escaped_word = html.escape(word)
    if category == "neutral":
        return f"🟡 {escaped_word}"

    return escaped_word


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


def get_month_rare_words(chat_id: int, year: int, month: int) -> tuple[str, ...]:
    seed = f"{chat_id}:{year}:{month}".encode()
    randomizer = Random(int.from_bytes(sha256(seed).digest(), "big"))

    return tuple(randomizer.sample(RARE_FIND_WORDS, k=RARE_WORDS_PER_MONTH))


def format_chat_comparison(swear_count: int, chat_swear_counts: list[int]) -> str:
    other_counts = list(chat_swear_counts)
    try:
        other_counts.remove(swear_count)
    except ValueError:
        pass
    if not other_counts:
        return "📍 Пока не с кем сравнить в этом месяце"

    lower_count = sum(1 for count in other_counts if count < swear_count)
    higher_count = sum(1 for count in other_counts if count > swear_count)

    if lower_count > higher_count:
        percent = round(lower_count / len(other_counts) * 100)
        return f"📍 Ты материшься больше {percent}% чата"
    if higher_count > lower_count:
        percent = round(higher_count / len(other_counts) * 100)
        return f"📍 Ты материшься меньше {percent}% чата"

    return "📍 Ты примерно в середине чата"


def _choose_special_profile_style(profile: SimpleNamespace) -> str | None:
    total_swears = profile.swear_count

    if total_swears == 0 and profile.neutral_count > 0:
        return "🟡 Интеллигентный токсик"
    if profile.neutral_count > total_swears:
        return "🟡 Интеллигентный токсик"
    if total_swears >= 8 and profile.favorite_count / total_swears >= 0.4:
        return "❤️ Верный классике"
    if total_swears >= 10 and profile.unique_swear_count >= min(8, total_swears):
        return "🎲 Лексический экспериментатор"
    if profile.previous_swear_count > 0:
        growth = (total_swears - profile.previous_swear_count) / profile.previous_swear_count
        if growth >= 0.5 and total_swears >= 10:
            return "📈 Набирает обороты"
        if growth <= -0.5 and profile.previous_swear_count >= 10:
            return "📉 Сдержался"

    return None


def _choose_index_profile_style(swear_index: float) -> str | None:
    if swear_index >= 15:
        return "☢️ Матный реактор"
    if swear_index >= 7:
        return "🚨 Опасная концентрация"
    if swear_index >= 3:
        return "🌶 Острый язык"

    return None


def _choose_count_profile_style(swear_count: int) -> str:
    if swear_count == 0:
        return "😇 Почти святой"
    if swear_count <= 3:
        return "🌱 Случайно вырвалось"
    if swear_count <= 10:
        return "🙂 Умеренно эмоциональный"
    if swear_count <= 25:
        return "🔥 Разогрелся"
    if swear_count <= 50:
        return "🎭 Эмоциональный критик"
    if swear_count <= 100:
        return "🏭 Заводской режим"
    return "💀 Легенда чата"


def choose_profile_style(profile: SimpleNamespace, swear_index: float) -> str:
    total_rude = profile.swear_count + profile.neutral_count

    if special_style := _choose_special_profile_style(profile):
        return special_style

    if index_style := _choose_index_profile_style(swear_index):
        return index_style

    if swear_index < 1 and total_rude > 0:
        return "🧊 Холодная голова"

    return _choose_count_profile_style(profile.swear_count)


def format_profile_report(username: str, year: int, month: int, profile: SimpleNamespace) -> str:
    total_rude = profile.swear_count + profile.neutral_count
    swear_index = (
        round(profile.swear_count / profile.message_count * 100, 1) if profile.message_count else 0
    )
    favorite_word = html.escape(profile.favorite_word) if profile.favorite_word else "пока нет"
    style = choose_profile_style(profile, swear_index)
    delta = format_percent_delta(profile.swear_count, profile.previous_swear_count)
    chat_comparison = format_chat_comparison(
        profile.swear_count,
        getattr(profile, "chat_swear_counts", []),
    )

    return (
        "🪪 <b>Матный профиль</b>\n\n"
        f"👤 {html.escape(username)}\n"
        f"📅 {MONTH_NAMES[month]} {year}\n\n"
        f"🔥 Матов: <b>{profile.swear_count}</b>\n"
        f"🟡 Мягких: <b>{profile.neutral_count}</b>\n"
        f"📊 Всего ругательств: <b>{total_rude}</b>\n\n"
        f"💬 Индекс: <b>{swear_index}%</b>\n"
        f"❤️ Любимый мат: <b>{favorite_word}</b>\n"
        f"🏆 Рекорд дня: <b>{profile.daily_record}</b>\n"
        f"📈 К прошлому месяцу: <b>{delta}</b>\n\n"
        f"{html.escape(chat_comparison)}\n"
        f"🎭 Стиль: <b>{style}</b>"
    )


async def announce_rare_find_if_needed(message: Message, found_words: list[str]) -> None:
    if not message.from_user or message.chat.type == "private":
        return

    now = message.date.astimezone(TZ_KYIV)
    rare_words = get_month_rare_words(message.chat.id, now.year, now.month)
    found_rare_words = [word for word in rare_words if word in found_words]

    if not found_rare_words:
        return

    for rare_word in found_rare_words:
        discovered = await BadWordsRepository.mark_rare_word_discovered(
            chat_id=message.chat.id,
            year=now.year,
            month=now.month,
            word=rare_word,
            user_id=message.from_user.id,
            username=message.from_user.full_name,
        )
        if not discovered:
            continue

        await message.answer(
            f"💎 Вы нашли редкую находку: <b>{html.escape(rare_word)}</b>",
            parse_mode="HTML",
        )


async def _remember_chat(message: Message) -> None:
    if message.chat.type == "private":
        return

    try:
        await BadWordsRepository.upsert_bot_chat(
            chat_id=message.chat.id,
            title=message.chat.title,
            chat_type=message.chat.type,
        )
    except RepositoryError:
        logger.exception("Не удалось сохранить название чата")


async def _is_user_chat_admin(message: Message, chat_id: int | str) -> bool:
    if not message.from_user:
        return False

    try:
        member = await message.bot.get_chat_member(chat_id, message.from_user.id)
    except Exception:
        logger.exception(f"Не удалось проверить права пользователя в чате {chat_id}")
        return False

    return member.status in {"creator", "administrator"}


async def _is_admin_or_private_chat(message: Message) -> bool:
    if not message.from_user:
        return False

    if message.chat.type == "private":
        return True

    try:
        member = await message.bot.get_chat_member(message.chat.id, message.from_user.id)
    except Exception:
        logger.exception(f"Не удалось проверить права пользователя в чате {message.chat.id}")
        return False

    return member.status in {"creator", "administrator"}


@router.message(CommandStart())
async def start_command_handler(message: Message):
    await message.answer("Добро пожаловать в бот, который будет считать ваши ругательства")


@router.message(Command("admin_swear_check"))
async def admin_swear_check_handler(message: Message):
    user = message.from_user
    if not user or user.is_bot or message.sender_chat or str(user.id) != settings.ADMIN_ID.strip():
        await message.answer("⛔ Команда доступна только владельцу бота.")
        return
    await message.answer(
        format_admin_build_report(RUNNING_BUILD, PROCESS_STARTED_AT, INSTANCE_NAME),
        parse_mode="HTML",
    )


@router.message(Command("subscribe_swears"))
async def subscribe_command_handler(message: Message):
    await _remember_chat(message)

    if not await _is_admin_or_private_chat(message):
        await message.answer("⛔ Подпиской на отчеты могут управлять только администраторы чата.")
        return

    success = await BadWordsRepository.subscribe_chat(message.chat.id)
    if success:
        ACTIVE_SUBSCRIPTIONS.inc()
        await message.answer(
            "✅ Этот чат подписан на отчеты: ежедневно, по понедельникам за неделю "
            "и первого числа за месяц. Отправка после 00:05 по Киеву."
        )
    else:
        await message.answer("ℹ️ Этот чат уже подписан на рассылку.")


@router.message(Command("unsubscribe_swears"))
async def unsubscribe_command_handler(message: Message):
    await _remember_chat(message)

    if not await _is_admin_or_private_chat(message):
        await message.answer("⛔ Подпиской на отчеты могут управлять только администраторы чата.")
        return

    success = await BadWordsRepository.unsubscribe_chat(message.chat.id)
    if success:
        ACTIVE_SUBSCRIPTIONS.dec()
        await message.answer("❌ Вы отписались. Отчеты больше приходить не будут.")
    else:
        await message.answer("ℹ️ Этот чат и так не был подписан на рассылку.")


@router.message(Command("count_swears"))
async def count_command_handler(message: Message):
    await _remember_chat(message)

    if not message.from_user:
        return

    request_date = datetime.now(TZ_KYIV).date()
    try:
        count = await BadWordsRepository.get_swear_count(
            chat_id=message.chat.id, user_id=message.from_user.id, date=request_date
        )

        count = count or 0
        logger.info(
            f"count command: chat_id={message.chat.id} "
            f"user_id={message.from_user.id} date={request_date} count={count}"
        )

        await message.answer(
            f"📊 {message.from_user.full_name}, у тебя сегодня {count} ругательств."
        )
    except Exception as e:
        logger.error(f"Ошибка получения статистики: {e}")
        await message.answer("⚠️ Не удалось получить статистику.")


@router.message(Command("profile_swears"))
async def profile_command_handler(message: Message):
    await _remember_chat(message)

    if not message.from_user:
        return

    now = datetime.now(TZ_KYIV)
    profile = await BadWordsRepository.get_user_month_profile(
        chat_id=message.chat.id,
        user_id=message.from_user.id,
        year=now.year,
        month=now.month,
    )

    await message.answer(
        format_profile_report(
            username=message.from_user.full_name,
            year=now.year,
            month=now.month,
            profile=profile,
        ),
        parse_mode="HTML",
    )


@router.message(Command("helpy_swears"))
async def help_command_handler(message: Message):
    await message.answer("К сожалению помощь не придет.")


@router.message(Command("chat_id"))
async def chat_id_command_handler(message: Message):
    await _remember_chat(message)

    await message.answer(f"ID этого чата: <code>{message.chat.id}</code>", parse_mode="HTML")


async def _answer_available_say_chats(message: Message) -> None:
    if not message.from_user:
        return

    available_chats = []
    for chat in await BadWordsRepository.get_all_bot_chats():
        if await _is_user_chat_admin(message, chat.chat_id):
            available_chats.append(chat)

    if not available_chats:
        await message.answer("Нету чатов, где вы админ.")
        return

    lines = ["Чаты, куда можно отправить сообщение:"]
    for chat in available_chats:
        title = html.escape(chat.title or str(chat.chat_id))
        lines.append(f"• <b>{title}</b>\n<code>/say {chat.chat_id} текст</code>")

    await message.answer("\n\n".join(lines), parse_mode="HTML")


@router.message(Command("say"))
async def say_command_handler(message: Message):
    if not message.from_user:
        return

    if message.chat.type != "private":
        await message.answer("Команда /say работает только в личке бота.")
        return

    target_chat_id, text = parse_say_command(message.text)
    if target_chat_id is None:
        await _answer_available_say_chats(message)
        return

    if not await _is_user_chat_admin(message, target_chat_id):
        await message.answer("Вы не админ в этом чате или бот не видит этот чат.")
        return

    try:
        await message.bot.send_message(chat_id=target_chat_id, text=text)
    except Exception:
        logger.exception("Ошибка отправки сообщения через /say")
        await message.answer("Не смог отправить сообщение в чат.")
        return

    await message.answer("Отправил.")


@router.message(Command("about_swears"))
async def about_command_handler(message: Message):
    await _remember_chat(message)

    text = (
        "🛡 <b>Swear Checker Bot (v0.1.4)</b>\n\n"
        "Инспектор чата 👮‍♂️\n"
        "Автоматический фильтр нецензурной лексики. Бот работает в фоновом режиме, "
        "анализирует сообщения и ведет статистику для каждого участника чата.\n\n"
        "<b>Особенности:</b>\n"
        "• Распознавание корней слов в любых склонениях.\n"
        "• Защита от обхода фильтра (Leetspeak, дублирование букв).\n"
        "• Персональная статистика и логирование.\n\n"
        "<b>Управление:</b>\n"
        "▫️ <code>/count_swears</code> — посмотреть количество своих матов за текущий день.\n"
        "▫️ <code>/week_swears</code> — статистика чата за текущую неделю.\n"
        "▫️ <code>/month_swears</code> — статистика чата за текущий месяц.\n"
        "▫️ <code>/profile_swears</code> — посмотреть свой матный профиль за месяц.\n"
        "▫️ <code>/logs_swears</code> — запросить детализацию (время и текст найденных ругательств)."
        "\n"
        "▫️ <code>/about_swears</code> — информация о боте.\n"
        "▫️ <code>/helpy_swears</code> — помощь.\n"
        "▫️ <code>/subscribe_swears</code> — подписаться на ежедневные отчеты (только для админов)."
        ".\n"
        "▫️ <code>/unsubscribe_swears</code> — отписаться от ежедневных отчетов.\n\n"
        "▫️ <code>/chat_id</code> — показать ID текущего чата.\n"
        "▫️ <code>/say</code> — в личке показать чаты, куда можно отправить сообщение.\n\n"
        "Автор бота: @Gamubells (Telegram)"
    )
    await message.answer(text, parse_mode="HTML")


@router.message(Command("logs_swears"))
async def logs_command_handler(message: Message):
    await _remember_chat(message)

    if not message.from_user:
        return

    logs = await BadWordsRepository.get_recent_logs(
        chat_id=message.chat.id, user_id=message.from_user.id, limit=30
    )

    if not logs:
        await message.answer("Ну ты и вежливый😇 Маты не обнаружены🧐")
        return

    today_kyiv = datetime.now(TZ_KYIV).date()
    text = (
        f"📜 <b>Твои ругательства за сегодня ({today_kyiv.strftime('%d.%m.%Y')})"
        f" — {html.escape(message.from_user.full_name)}:</b>\n\n"
    )

    grouped_logs = {}

    for log in logs:
        time_kyiv = log.timestamp.astimezone(TZ_KYIV)
        time_str = time_kyiv.strftime("%H:%M")

        if time_str not in grouped_logs:
            grouped_logs[time_str] = []

        grouped_logs[time_str].append(format_log_word(log.word, log.category))

    for time_str in sorted(grouped_logs.keys()):
        words_joined = ", ".join(grouped_logs[time_str])
        text += f"[{time_str}] <b>{words_joined}</b>\n"

    await message.answer(text, parse_mode="HTML")


@router.message(Command("week_swears", "month_swears"))
async def period_command_handler(message: Message):
    today = datetime.now(TZ_KYIV).date()
    command = (message.text or "").split()[0].split("@")[0]
    start = (
        today.replace(day=1)
        if command == "/month_swears"
        else (today - timedelta(days=today.weekday()))
    )
    records = await BadWordsRepository.get_all_for_period(
        message.chat.id, start, today + timedelta(days=1)
    )
    report = (
        format_monthly_report(records, today.year, today.month)
        if command == "/month_swears"
        else format_weekly_report(records, start, today + timedelta(days=1))
    )
    for chunk in split_telegram_message(report):
        await message.answer(chunk)


@router.error()
async def repository_error_handler(event: ErrorEvent):
    if not isinstance(event.exception, RepositoryError):
        raise event.exception
    logger.opt(exception=event.exception).error("Ошибка базы данных при обработке сообщения")
    message = event.update.message or event.update.edited_message
    if message and message.text and message.text.startswith("/"):
        await message.answer("⚠️ База данных временно недоступна. Попробуй ещё раз позже.")
    return True


@router.edited_message()
@router.message(F.text | F.caption)
async def bad_words_handler(message: Message, event_update: Update | None = None):
    if not message.from_user or message.from_user.is_bot or message.sender_chat:
        return
    MESSAGES_TOTAL.inc()
    await _remember_chat(message)
    content = message.text or message.caption or ""
    swear_check = check_text_for_swears_detailed(content)
    version = message.edit_date or message.date
    if isinstance(version, int):
        version = datetime.fromtimestamp(version, TZ_KYIV)
    changed = await BadWordsRepository.record_message(
        chat_id=message.chat.id,
        message_id=message.message_id,
        user_id=message.from_user.id,
        username=message.from_user.full_name,
        timestamp=message.date,
        version=version,
        swear_words=swear_check.swear_words,
        neutral_words=swear_check.neutral_words,
        edited=message.edit_date is not None,
        update_id=event_update.update_id if event_update else 0,
    )
    if changed:
        SWEARS_TOTAL.inc(swear_check.swear_count)
        await announce_rare_find_if_needed(message, swear_check.swear_words)
