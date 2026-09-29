from prometheus_client import Counter, Gauge


MESSAGES_TOTAL = Counter("bot_messages_total", "Общее количество полученных текстовых сообщений")

SWEARS_TOTAL = Counter("bot_swears_total", "Общее количество заблокированных матерных слов")

ACTIVE_SUBSCRIPTIONS = Gauge(
    "bot_active_subscriptions", "Текущее количество чатов с подпиской на отчеты"
)

INSTANCE_LOCK_HEALTHY = Gauge("bot_instance_lock_healthy", "Exclusive database lock is held")
POLLING_STARTED = Gauge("bot_polling_started_timestamp", "Polling start time, Unix seconds")
POLLING_LAST_SUCCESS = Gauge(
    "bot_polling_last_success_timestamp", "Last successful getUpdates response, Unix seconds"
)
POLLING_LAST_CONFLICT = Gauge(
    "bot_polling_last_conflict_timestamp", "Last conflicting getUpdates request, Unix seconds"
)
