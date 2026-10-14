#!/usr/bin/env python3
"""Post the day's saints and feasts that have a written life, with their
apolytikion and kontakion, from the Greek Orthodox Archdiocese of America's
Online Chapel to a Discord channel webhook.

Usage:
    python3 post_saints.py                    # today's saints
    python3 post_saints.py --date 2026-12-25  # a specific day
    python3 post_saints.py --dry-run          # print the payloads, post nothing
"""

from common import (
    Bot,
    daily_feed,
    english,
    fetch_xml,
    format_date,
    html_to_text,
    https,
    MAX_FOOTER,
    MAX_TITLE,
    pack_embeds,
    run,
    text_embeds,
)

SAINT_URL = "https://onlinechapel.goarch.org/saints.asp?contentid={id}"
# Most commemorations without their own icon fall back to this generic one.
PLACEHOLDER_ICON = "small/allsaint.jpg"
COLOR = 0x6B4E9B
# The feed ranks commemorations with lower numbers for greater feasts
# (0 is Pascha, 10 an ordinary saint); anything unranked sorts last.
UNRANKED = 99


def fetch_saints(date):
    """Return the formatted date and the day's commemorations that have a life,
    greatest feast first."""
    saints = []
    for entry in daily_feed(date).iter("saintfeast"):
        # The feed's moreinfo flag is set on some entries that have hymns but
        # no life, so check for the life itself.
        detail = fetch_xml(SAINT_URL.format(id=entry.findtext("id")))
        life = english(detail.find("readings"))
        text = html_to_text(life.findtext("body")) if life is not None else ""
        if not text:
            continue

        icon = detail.find("icons/icon")
        has_own_icon = icon is not None and icon.findtext("filepath") != PLACEHOLDER_ICON
        hymns = []
        for hymn in detail.iter("hymn"):
            translation = english(hymn)
            if translation is None or not translation.findtext("body"):
                continue
            hymns.append(
                {
                    "type": (hymn.findtext("type") or "Hymn").title(),
                    "tone": hymn.findtext("tone"),
                    "text": html_to_text(translation.findtext("body")),
                    "copyright": translation.findtext("copyright"),
                }
            )
        rank = entry.findtext("classification") or ""
        saints.append(
            {
                "name": entry.findtext("title") or detail.findtext("title"),
                "link": https(entry.findtext("publicurl")),
                "rank": int(rank) if rank.isdigit() else UNRANKED,
                "life": text,
                "life_copyright": life.findtext("copyright"),
                "icon_url": https(icon.findtext("url")) if has_own_icon else None,
                "icon_copyright": icon.findtext("copyright") if has_own_icon else None,
                "hymns": hymns,
            }
        )
    saints.sort(key=lambda saint: saint["rank"])  # stable, so ties keep feed order
    return {"formatted_date": format_date(date), "saints": saints}


def saint_text(saint):
    parts = [saint["life"]]
    for hymn in saint["hymns"]:
        heading = hymn["type"]
        if hymn["tone"]:
            heading += f" ({hymn['tone']})"
        parts.append(f"**{heading}**\n{hymn['text']}")
    return "\n\n".join(parts)


def saint_footer(saint):
    parts = []
    if saint["life_copyright"]:
        parts.append(f"Life: {saint['life_copyright']}")
    hymn_copyrights = list(dict.fromkeys(h["copyright"] for h in saint["hymns"] if h["copyright"]))
    if hymn_copyrights:
        parts.append(f"Hymns: {', '.join(hymn_copyrights)}")
    if saint["icon_copyright"]:
        parts.append(f"Icon: {saint['icon_copyright']}")
    return " · ".join(parts)


def saint_embeds(saint):
    first = {"title": saint["name"][:MAX_TITLE], "url": saint["link"]}
    if saint["icon_url"]:
        first["thumbnail"] = {"url": saint["icon_url"]}
    embeds = text_embeds(saint_text(saint), COLOR, first, f"{saint['name']} (continued)")
    footer = saint_footer(saint)
    if footer:
        embeds[-1]["footer"] = {"text": footer[:MAX_FOOTER]}
    return embeds


def build_messages(day):
    if not day["saints"]:
        return []
    embeds = [embed for saint in day["saints"] for embed in saint_embeds(saint)]
    return pack_embeds(embeds, f"**{day['formatted_date']}**")


BOT = Bot(
    name="saints",
    description=__doc__.split("\n\n")[0],
    build_messages_for=lambda date: build_messages(fetch_saints(date)),
    webhook_env="DISCORD_SAINTS_WEBHOOK_URL",
    username_env="SAINTS_BOT_USERNAME",
    default_username="Saints of the Day",
)


if __name__ == "__main__":
    run(BOT)
