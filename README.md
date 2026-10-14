# discord-bot

Two daily Discord posts from the Greek Orthodox Archdiocese of America's Online Chapel feed (`onlinechapel.goarch.org`), each to its own channel through a channel webhook. The feed follows the GOA calendar, including the Lukan Jump.

- **Readings** (`post_readings.py`): the Matins Gospel (on Sundays and feasts, with the Eothinon number on ordinary Sundays), the Epistle with its prokeimenon, and the Gospel, each linked to its page on goarch.org. On days with no Epistle or Gospel, such as Lenten weekdays, it posts a short note listing that day's other readings.
- **Saints** (`post_saints.py`): each saint or feast of the day that has a written life, greatest feast first, with its apolytikion and kontakion and its icon when it has its own (not the generic All Saints placeholder). Commemorations without a life are left out, and nothing is posted on a day without any.

Long texts, like the Holy Thursday Gospel, are split across messages. `common.py` holds the shared feed, formatting, and posting code.

Python 3.9+ standard library only. No dependencies to install.

## Setup

1. For each channel, open its settings in Discord, then **Integrations > Webhooks > New Webhook**, and copy the webhook URL.
2. `cp .env.example .env` and paste the URLs after `DISCORD_WEBHOOK_URL=` (readings) and `DISCORD_SAINTS_WEBHOOK_URL=` (saints).

## Usage

```bash
python3 post_readings.py --dry-run                   # print today's payloads, post nothing
python3 post_saints.py --dry-run --date 2026-08-15   # any date
python3 post_readings.py                             # post today's readings
```

"Today" is computed in `BOT_TIMEZONE` (default `America/Chicago`).

## Tests

```bash
python3 -m unittest discover -s tests
```

## Running on a Windows PC

`run_daily.py` posts both once a day from an always-on machine. A marker file per post per day (in `state/`) means a second run the same day only posts what's missing, and failed posts retry every 10 minutes for about an hour. Everything is logged to `logs/daily.log`.

1. Install Python 3.9 or newer from python.org (it includes the `py` launcher).
2. Clone this repo, then `copy .env.example .env` and fill in both webhook URLs.
3. In PowerShell opened with **Run as administrator**, from the repo folder:
   ```powershell
   powershell -ExecutionPolicy Bypass -File windows\install-task.ps1
   ```
   This installs the `tzdata` package (Python on Windows has no time zone data of its own), runs a setup check that posts nothing, and registers a Task Scheduler task that runs at 7:00 AM daily, starting tomorrow. The task runs whether or not you're signed in, wakes the PC from sleep, and runs as soon as it can after a missed start. Add `-Time 06:30` to pick another time.
4. For waking from sleep to work, the power plan must allow wake timers (Control Panel > Power Options > Change plan settings > Change advanced power settings > Sleep > Allow wake timers).

To check setup by hand at any time: `py -3 run_daily.py --dry-run`. After pulling changes, nothing needs reinstalling unless the install script itself changed. Don't run this and the GitHub schedule at the same time; they can't see each other's markers, so both would post.

## Schedule

`.github/workflows/post-readings.yml` posts both at 7:05 AM Central every day, with backup runs at :35 past each hour until late morning. GitHub delays scheduled runs under load and sometimes drops them, so each run checks whether today's posts already went out (a small per-day marker in the Actions cache) and posts only what's missing. GitHub cron runs in UTC, so the times cover both daylight saving time and winter, and any run before 7 AM Central does nothing. If one post fails, the other still runs, and the next backup retries the failed one.

It reads the webhook URLs from the `DISCORD_WEBHOOK_URL` and `DISCORD_SAINTS_WEBHOOK_URL` repository secrets. To post by hand, for a specific date, or only one of the two, run the workflow from the Actions tab (or `gh workflow run post-readings.yml -f date=2026-12-25 -f post=saints`). Runs started by hand always post; when they post today's, the scheduled runs skip it.
