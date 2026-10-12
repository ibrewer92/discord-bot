#!/usr/bin/env python3
"""Post the day's Matins Gospel, Epistle, and Gospel readings from the Greek
Orthodox Archdiocese of America's Online Chapel to a Discord channel webhook.

Usage:
    python3 post_readings.py                    # today's readings
    python3 post_readings.py --date 2026-12-25  # a specific day
    python3 post_readings.py --dry-run          # print the payloads, post nothing
"""

from common import (
    daily_feed,
    english,
    escape_markdown,
    fetch_xml,
    format_date,
    html_to_text,
    https,
    MAX_TITLE,
    pack_embeds,
    run,
    text_embeds,
)

# The feed lists a Matins Gospel (MG) on Sundays and major feasts. Old
# Testament readings (OT) are not posted.
READING_TYPES = {"MG": "Matins Gospel", "E": "Epistle", "G": "Gospel"}
COLORS = {"MG": 0x2E5A88, "E": 0x8B1E3F, "G": 0xC9A227}
FOOTER = "Greek Orthodox Archdiocese of America · Online Chapel"


def fetch_day(date):
    """Return the day's title, formatted date, readings to post, and other readings."""
    feed = daily_feed(date)
    eothinon = feed.findtext("eothinon") or ""
    readings, others = [], []
    for reading in feed.iter("reading"):
        kind = reading.findtext("type")
        listing = english(reading)
        title = listing.findtext("title") if listing is not None else kind
        link = https(reading.findtext("publicurl"))
        if kind not in READING_TYPES:
            others.append({"title": title, "link": link})
            continue

        label = READING_TYPES[kind]
        # A number on ordinary Sundays; "Festal" or blank on feasts.
        if kind == "MG" and eothinon.isdigit():
            label += f" · Eothinon {eothinon}"
        full = english(fetch_xml(https(reading.findtext("url"))))
        text = html_to_text(full.findtext("body")) if full is not None else ""
        prokeimenon = None
        if full is not None and full.findtext("prokprokeimenon"):
            prokeimenon = {
                "mode": full.findtext("prokmode"),
                "text": full.findtext("prokprokeimenon"),
                "verse": full.findtext("prokverse"),
            }
        readings.append(
            {
                "kind": kind,
                "label": label,
                "title": full.findtext("title") if full is not None else title,
                "link": link,
                "prokeimenon": prokeimenon,
                "text": text,
            }
        )
    return {
        "formatted_date": format_date(date),
        "lectionary_title": feed.findtext("lectionarytitle") or "",
        "readings": readings,
        "others": others,
    }


def prokeimenon_block(prokeimenon):
    if not prokeimenon:
        return ""
    heading = "Prokeimenon"
    if prokeimenon["mode"]:
        heading += f" (Mode {prokeimenon['mode']})"
    lines = [f"*{heading}:* {escape_markdown(prokeimenon['text'])}"]
    if prokeimenon["verse"]:
        lines.append(f"*{escape_markdown(prokeimenon['verse'])}*")
    return "\n".join(lines) + "\n\n"


def reading_embeds(reading):
    label = reading["label"]
    body = reading["text"] or f"Full text unavailable. [Read it on goarch.org]({reading['link']})"
    first = {"author": {"name": label}, "title": reading["title"][:MAX_TITLE], "url": reading["link"]}
    return text_embeds(
        prokeimenon_block(reading["prokeimenon"]) + body,
        COLORS[reading["kind"]],
        first,
        f"{label} (continued)",
    )


def build_messages(day):
    header = f"**{day['formatted_date']}**"
    if day["lectionary_title"]:
        header += f"\n{day['lectionary_title']}"

    if not day["readings"]:
        lines = [header, "", "No Epistle or Gospel is appointed for today."]
        if day["others"]:
            lines.append("Today's readings:")
            lines += [f"- [{other['title']}](<{other['link']}>)" for other in day["others"]]
        return [{"content": "\n".join(lines)}]

    embeds = [embed for reading in day["readings"] for embed in reading_embeds(reading)]
    embeds[-1]["footer"] = {"text": FOOTER}
    return pack_embeds(embeds, header)


if __name__ == "__main__":
    run(
        __doc__.split("\n\n")[0],
        lambda date: build_messages(fetch_day(date)),
        webhook_env="DISCORD_WEBHOOK_URL",
        username_env="READINGS_BOT_USERNAME",
        default_username="Daily Readings",
    )
