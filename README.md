# discord-bot

Posts the day's Matins Gospel, Epistle, and Gospel readings (Greek Orthodox Archdiocese of America lectionary) to a Discord channel through a channel webhook.

Readings come from the GOA Online Chapel feed (`onlinechapel.goarch.org/daily.asp`), which follows the GOA calendar, including the Lukan Jump. Each post has the day's title, the Matins Gospel (on Sundays and feasts, with the Eothinon number on ordinary Sundays), the Epistle with its prokeimenon, and the Gospel, each linked to its page on goarch.org. Long readings, like the Holy Thursday Gospel, are split across messages. On days with no Epistle or Gospel, such as Lenten weekdays, it posts a short note listing that day's other readings.

Python 3.9+ standard library only. No dependencies to install.

## Setup

1. In Discord, open the channel's settings, then **Integrations > Webhooks > New Webhook**, and copy the webhook URL.
2. `cp .env.example .env` and paste the URL after `DISCORD_WEBHOOK_URL=`.

## Usage

```bash
python3 post_readings.py --dry-run                   # print today's payloads, post nothing
python3 post_readings.py --dry-run --date 2027-04-29 # any date
python3 post_readings.py                             # post today's readings
```

"Today" is computed in `READINGS_TIMEZONE` (default `America/Chicago`).

## Tests

```bash
python3 -m unittest discover -s tests
```

## Schedule

`.github/workflows/post-readings.yml` posts at 7:00 AM Central every day. GitHub cron runs in UTC, so the workflow has one line for daylight saving time and one for winter, and a gate step lets only the matching one post. Scheduled runs can start 5 to 30 minutes late.

It reads the webhook URL from the `DISCORD_WEBHOOK_URL` repository secret. To post by hand, or for a specific date, run the workflow from the Actions tab (or `gh workflow run post-readings.yml -f date=2026-12-25`).
