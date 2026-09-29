# 🤬 Telegram Swear Moderation Bot

![Python Version](https://img.shields.io/badge/python-3.12-blue.svg)
![aiogram Version](https://img.shields.io/badge/aiogram-3.27-blue.svg)
![PostgreSQL](https://img.shields.io/badge/PostgreSQL-15-blue.svg)
![Docker](https://img.shields.io/badge/Docker-ready-blue.svg)

**Telegram Swear Moderation Bot** is an asynchronous Telegram moderation bot that detects profanity in group chats, keeps detailed statistics for each user, and sends daily reports.

The bot is designed for performance. It uses asynchronous database access with SQLAlchemy and asyncpg, precompiled regular expressions, and a service-oriented architecture.

## ✨ Key Features

- 🧠 **Smart detection:** Recognizes profane word roots across different inflections as well as exact matches.
- 🛡️ **Evasion resistance:** Detects leetspeak substitutions (for example, `@` instead of `а`) and repeated characters such as `пппиииззздддеееццц`.
- 📊 **Chat subscriptions:** Chats can subscribe to automatic daily statistics reports.
- 🪪 **User profiles:** Users can request a compact monthly summary with their profanity index, most-used swear word, daily record, and monthly style.
- 📈 **Monthly trends:** End-of-month reports compare results with the previous month and highlight the month's most-used swear word and most active day.
- 💎 **Rare finds:** The bot automatically selects three rare words for each chat every month and posts a short message when a user finds one first.
- ⏰ **Reports:** Daily, weekly (Monday), and monthly (first day) reports cover complete
  calendar periods and become due at 00:05 Kyiv time. Delivery is checked every five minutes.
- 🔁 **Recovery:** Delivery progress survives restarts; failed or unfinished reports are retried.
- ✏️ **Message edits:** Text and media captions are counted; edits update the original day's
  totals without counting the message twice.
- 🐳 **Easy deployment:** Ready to run with Docker and Docker Compose.

## 🛠 Technology Stack

- **Language:** Python 3.12
- **Framework:** aiogram 3.x
- **Database:** PostgreSQL
- **ORM:** SQLAlchemy 2.0 (asyncio) + asyncpg
- **Scheduler:** APScheduler
- **Dependency management:** Poetry
- **Infrastructure:** Docker, Docker Compose

## 🚀 Installation and Docker Setup

This is the fastest and recommended way to run the bot on a server.

1. **Clone the repository:**

   ```bash
   git clone https://github.com/Gamubells/telegram-SwearModeration-bot.git
   cd telegram-SwearModeration-bot
   ```

2. **Configure environment variables:**

   Copy the example configuration and add your credentials, including the bot token from [@BotFather](https://t.me/BotFather):

   ```bash
   cp .env.example .env
   ```

   Make sure `DB_HOST=db` is set in `.env` when running with Docker.

3. **Start the containers:**

   ```bash
   docker compose up -d
   ```

4. **Check the logs (optional):**

   ```bash
   docker compose logs -f bot
   ```

## 💻 Local Development

Local development requires PostgreSQL and Poetry.

1. **Install dependencies:**

   ```bash
   poetry install
   ```

2. **Configure the `.env` file:**

   Use `DB_HOST=localhost` for a local database.

3. **Run the bot:**

   ```bash
   poetry run python app.py
   ```

## 📱 Bot Commands

- `/start` — Display a welcome message and verify that the bot is running.
- `/count_swears` — Show your profanity count for today.
- `/profile_swears` — Show your profanity profile for the current month.
- `/logs_swears` — Show a detailed log of detected profanity for the day, including time and message text.
- `/week_swears` — Show the chat's current calendar week, including today.
- `/month_swears` — Show the chat's current calendar month, including today.
- `/subscribe_swears` — Subscribe the current chat to daily, weekly, and monthly reports (admins only in groups).
- `/unsubscribe_swears` — Unsubscribe the current chat from all automatic reports.
- `/about_swears` — Show information about the bot and its author.
- `/admin_swear_check` — Show the running release, commit date, image build time,
  process start time, code fingerprint, and instance name. Only the user configured
  in `ADMIN_ID` can use this command, including in private chats.

### Checking whether the running bot was updated

Send `/admin_swear_check` to the bot from the `ADMIN_ID` account. Compare its commit
with the latest GitHub commit, or its code fingerprint with `poetry run python version_info.py`
in the corresponding checkout. The command describes the code loaded at startup:
pulling new files without restarting the process does not change its reported release.
Build time and process start time are labelled separately from the commit date.

Docker builds automatically embed the build date and code fingerprint. To include
the exact Git commit and its date when building an image manually:

```bash
docker compose build \
  --build-arg VCS_REF="$(git rev-parse HEAD)" \
  --build-arg VCS_DATE="$(git show -s --format=%cI HEAD)" bot
```

Without these build arguments, Git details are reported as unavailable; build time
and the fingerprint remain available. The command does not contact GitHub or update
the bot. It becomes available only after this version is installed on the active server.
Automatic deployment to Proxmox remains disabled.

## 🗂 Project Structure

The project follows separation-of-concerns principles:

- `app.py` — Application entry point and scheduler initialization.
- `handlers/` — Telegram routers and command handlers.
- `services.py` — Business logic, precompiled regular expressions, and text parsing.
- `database/` — SQLAlchemy configuration, models, and CRUD repositories.
- `scheduler.py` — Scheduled report generation and delivery.
- `bad_words_list.py` — Dictionaries and character mappings used for filtering.

## 🐛 Troubleshooting

If you experience database connection or word-counting issues, see [DEBUGGING.md](DEBUGGING.md) for solutions to common problems.

### Report delivery and upgrades

- A PostgreSQL session lock permits one active instance per bot ID and database.
  Other copies wait without polling or sending scheduled reports. A lost lock connection
  stops the bot before it can continue without ownership.
- Identical error notifications are limited to one per 15 minutes; all occurrences stay
  in the file and console logs. `python healthcheck.py` checks successful polling,
  recent conflicts, and lock ownership.
- Automatic deployment to Proxmox is temporarily disabled. Pushes to `master` or `main`
  run Ruff and pytest only; they do not start or update the bot container.
- A conflicting instance using a different database cannot be stopped by this lock.
  Stop that instance, or revoke the old token in BotFather and configure a new token
  only on the intended server. Do not run `getUpdates` manually against a running bot.

- Existing subscriptions are preserved. An admin can run `/subscribe_swears` in a group
  to enable all report periods. The bot must be able to send messages there. To count all
  group messages, make it an admin or disable Group Privacy in BotFather.
- At startup the bot initializes the database before starting the scheduler and preserves
  pending Telegram updates. The latest completed day, week, and month are recovered;
  it does not send every historical period missed during a long outage.
- Delivery snapshots and the last successfully sent part are stored in PostgreSQL.
  A crash between Telegram accepting a part and the database recording success can still
  duplicate that part on retry; Telegram does not provide an idempotency key for sending.
- New tables `processed_messages` and `report_deliveries`, plus a nullable
  `swear_logs.message_id` column, are created automatically. Existing counters remain intact.
  Rollback: restore the previous application version and leave these additive structures in place.
- Word logs and message baselines are retained for at least 90 days, covering the current
  and previous full months. Previously deleted logs cannot be reconstructed from counters.
  Edits to messages sent before this upgrade (without a saved baseline) are ignored to avoid
  double counting. Already delivered reports are snapshots and are not resent after edits.
- Dictionary additions were selected from messages dated January 1–September 16, 2026.
  The private chat export, author identities, and original messages are not included here.

### Verification

Run `poetry run pytest`, `poetry run ruff check .`, and `poetry run ruff format --check .`.
Tests use dummy credentials. Integration tests start and stop a separate temporary PostgreSQL
cluster when server binaries are available (otherwise those tests are skipped); they never
connect to the database configured in `.env`.
