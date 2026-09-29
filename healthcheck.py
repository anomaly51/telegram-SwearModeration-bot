import sys
import time
import urllib.request


def polling_is_healthy(metrics: str, now: float) -> bool:
    values = {}
    for line in metrics.splitlines():
        if line.startswith("bot_"):
            key, _, value = line.partition(" ")
            try:
                values[key] = float(value)
            except ValueError:
                continue
    last_success = values.get("bot_polling_last_success_timestamp", 0)
    last_conflict = values.get("bot_polling_last_conflict_timestamp", 0)
    started = values.get("bot_polling_started_timestamp", 0)
    return (
        values.get("bot_instance_lock_healthy") == 1
        and started > 0
        and now - started >= 60
        and last_success > 0
        and 0 <= now - last_success <= 90
        and (last_conflict == 0 or now - last_conflict >= 60)
    )


def main():
    try:
        with urllib.request.urlopen("http://127.0.0.1:8000/metrics", timeout=3) as response:
            healthy = polling_is_healthy(response.read().decode(), time.time())
    except (OSError, ValueError):
        healthy = False
    print("Polling healthy" if healthy else "Polling unavailable or conflicting")
    return 0 if healthy else 1


if __name__ == "__main__":
    sys.exit(main())
