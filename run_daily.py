#!/usr/bin/env python3
"""Post today's readings and saints once each, for a scheduler on an
always-on machine (see windows/install-task.ps1).

A marker file per post per day means running it again the same day, or
after a missed start, only posts what hasn't gone out yet. If a post
fails, it waits and retries for about an hour before giving up. Each run
appends to logs/daily.log.

Usage:
    python3 run_daily.py            # post whatever hasn't gone out today
    python3 run_daily.py --dry-run  # check settings, feed access, and today's messages; post nothing
"""

import argparse
import datetime as dt
import sys
import time
import traceback
from pathlib import Path

import common
import post_readings
import post_saints

BOTS = [post_readings.BOT, post_saints.BOT]
HERE = Path(__file__).resolve().parent
STATE_DIR = HERE / "state"
LOG_FILE = HERE / "logs" / "daily.log"
ATTEMPTS = 7
RETRY_WAIT_SECONDS = 10 * 60
KEEP_MARKERS = dt.timedelta(days=30)


def log(message):
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {message}"
    print(line, flush=True)
    LOG_FILE.parent.mkdir(exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as file:
        file.write(line + "\n")


def marker(bot, date):
    return STATE_DIR / f"posted-{bot.name}-{date.isoformat()}"


def post_pending(bots, date):
    """Post each bot that hasn't posted for `date` yet. Returns the ones that failed."""
    failed = []
    for bot in bots:
        if marker(bot, date).exists():
            log(f"{bot.name}: already posted for {date}")
            continue
        try:
            count = bot.post(date)
        except Exception as error:  # feed, network, or Discord trouble; retried later
            log(f"{bot.name}: failed: {type(error).__name__}: {error}")
            failed.append(bot)
            continue
        STATE_DIR.mkdir(exist_ok=True)
        marker(bot, date).write_text(f"{dt.datetime.now().isoformat()}\n", encoding="utf-8")
        log(f"{bot.name}: posted {count} message(s) for {date}" if count else f"{bot.name}: nothing to post for {date}")
    return failed


def prune_markers(today):
    for path in STATE_DIR.glob("posted-*"):
        try:
            day = dt.date.fromisoformat(path.name[-10:])
        except ValueError:
            continue
        if today - day > KEEP_MARKERS:
            path.unlink()


def check_setup(date):
    ok = True
    for bot in BOTS:
        try:
            bot.webhook_url()
        except common.PostError as error:
            log(f"{bot.name}: {error}")
            ok = False
        try:
            messages = bot.build_messages_for(date)
        except Exception as error:
            log(f"{bot.name}: couldn't build today's post: {type(error).__name__}: {error}")
            ok = False
        else:
            log(f"{bot.name}: {len(messages)} message(s) ready for {date}")
    log("Setup check passed." if ok else "Setup check failed.")
    return ok


def main():
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="check settings, feed access, and today's messages without posting",
    )
    args = parser.parse_args()

    common.load_env()
    date = common.today()
    if args.dry_run:
        return 0 if check_setup(date) else 1

    pending = BOTS
    for attempt in range(1, ATTEMPTS + 1):
        pending = post_pending(pending, date)
        if not pending or attempt == ATTEMPTS:
            break
        log(f"Retrying in {RETRY_WAIT_SECONDS // 60} minutes.")
        time.sleep(RETRY_WAIT_SECONDS)
    prune_markers(date)
    if pending:
        log("Gave up on: " + ", ".join(bot.name for bot in pending))
        return 1
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception:
        # Under Task Scheduler nobody sees the console, so make sure the log has it.
        log(traceback.format_exc())
        sys.exit(1)
