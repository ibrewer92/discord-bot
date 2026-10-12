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

## Schedule

`.github/workflows/post-readings.yml` posts both at 7:05 AM Central every day, with backup runs at :35 past each hour until late morning. GitHub delays scheduled runs under load and sometimes drops them, so each run checks whether today's posts already went out (a small per-day marker in the Actions cache) and posts only what's missing. GitHub cron runs in UTC, so the times cover both daylight saving time and winter, and any run before 7 AM Central does nothing. If one post fails, the other still runs, and the next backup retries the failed one.

It reads the webhook URLs from the `DISCORD_WEBHOOK_URL` and `DISCORD_SAINTS_WEBHOOK_URL` repository secrets. To post by hand, for a specific date, or only one of the two, run the workflow from the Actions tab (or `gh workflow run post-readings.yml -f date=2026-12-25 -f post=saints`). Runs started by hand always post; when they post today's, the scheduled runs skip it.
