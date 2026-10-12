#!/usr/bin/env python3
"""Post the day's Epistle and Gospel readings from the Greek Orthodox
Archdiocese of America's Online Chapel to a Discord channel webhook.

Usage:
    python3 post_readings.py                    # today's readings
    python3 post_readings.py --date 2026-12-25  # a specific day
    python3 post_readings.py --dry-run          # print the payloads, post nothing
"""

import argparse
import datetime as dt
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo

FEED_URL = "https://onlinechapel.goarch.org/daily.asp?date={date}"
USER_AGENT = "discord-lectionary-bot/1.0 (personal use)"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# The feed lists a Matins Gospel (MG) on Sundays and major feasts. Old
# Testament readings (OT) are not posted.
READING_TYPES = {"MG": "Matins Gospel", "E": "Epistle", "G": "Gospel"}
COLORS = {"MG": 0x2E5A88, "E": 0x8B1E3F, "G": 0xC9A227}
FOOTER = "Greek Orthodox Archdiocese of America · Online Chapel"

# Discord embed limits: https://discord.com/developers/docs/resources/message#embed-object-embed-limits
MAX_DESCRIPTION = 4096
MAX_EMBEDS_PER_MESSAGE = 10
MAX_EMBED_CHARS_PER_MESSAGE = 6000


def load_dotenv(path):
    if not path.exists():
        return
    for line in path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def fetch_xml(url, attempts=3):
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    for attempt in range(1, attempts + 1):
        try:
            with urllib.request.urlopen(request, timeout=30) as response:
                return ET.fromstring(response.read())
        except (urllib.error.URLError, TimeoutError, ET.ParseError):
            if attempt == attempts:
                raise
            time.sleep(5 * attempt)


def https(url):
    return re.sub(r"^http://", "https://", url or "")


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag == "p":
            self.parts.append("\n\n")

    def handle_data(self, data):
        # Newlines in HTML source are just whitespace; only <p> and <br> break lines.
        self.parts.append(re.sub(r"\s+", " ", data))


def html_to_text(html):
    extractor = _TextExtractor()
    extractor.feed(html or "")
    text = "".join(extractor.parts)
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text):
        lines = [" ".join(line.split()) for line in paragraph.split("\n")]
        paragraph = "\n".join(line for line in lines if line)
        if paragraph:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


def english(element):
    for translation in element.findall("translation"):
        if translation.get(XML_LANG) == "en":
            return translation
    return None


def fetch_day(date):
    """Return the day's title, formatted date, readings to post, and other readings."""
    feed = fetch_xml(FEED_URL.format(date=date.strftime("%m/%d/%Y")))
    eothinon = feed.findtext("eothinon")
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
        # The feed's own formatteddate zero-pads some days ("May 02").
        "formatted_date": f"{date:%A, %B} {date.day}, {date:%Y}",
        "lectionary_title": feed.findtext("lectionarytitle") or "",
        "readings": readings,
        "others": others,
    }


SENTENCE_END = re.compile(r"[.!?;:][\"'”’)]*\s")


def split_text(text, limit):
    """Split text into chunks of at most `limit` chars, preferring paragraph,
    then sentence, then word boundaries."""
    chunks = []
    while len(text) > limit:
        window = text[:limit]
        cut = window.rfind("\n\n")
        if cut < limit // 2:
            ends = [match.end() for match in SENTENCE_END.finditer(window)]
            cut = ends[-1] if ends and ends[-1] >= limit // 2 else window.rfind(" ")
        if cut <= 0:
            cut = limit
        chunks.append(text[:cut].rstrip())
        text = text[cut:].lstrip()
    if text:
        chunks.append(text)
    return chunks


def prokeimenon_block(prokeimenon):
    if not prokeimenon:
        return ""
    heading = "Prokeimenon"
    if prokeimenon["mode"]:
        heading += f" (Mode {prokeimenon['mode']})"
    lines = [f"*{heading}:* {prokeimenon['text']}"]
    if prokeimenon["verse"]:
        lines.append(f"*{prokeimenon['verse']}*")
    return "\n".join(lines) + "\n\n"


def reading_embeds(reading):
    label = reading["label"]
    body = reading["text"] or f"Full text unavailable. [Read it on goarch.org]({reading['link']})"
    chunks = split_text(prokeimenon_block(reading["prokeimenon"]) + body, MAX_DESCRIPTION)
    embeds = []
    for index, chunk in enumerate(chunks):
        embed = {"color": COLORS[reading["kind"]], "description": chunk}
        if index == 0:
            embed["author"] = {"name": label}
            embed["title"] = reading["title"][:256]
            embed["url"] = reading["link"]
        else:
            embed["author"] = {"name": f"{label} (continued)"}
        embeds.append(embed)
    return embeds


def embed_size(embed):
    return sum(
        len(value)
        for value in (
            embed.get("title", ""),
            embed.get("description", ""),
            embed.get("author", {}).get("name", ""),
            embed.get("footer", {}).get("text", ""),
        )
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

    messages, current, size = [], [], 0
    for embed in embeds:
        if current and (
            len(current) == MAX_EMBEDS_PER_MESSAGE
            or size + embed_size(embed) > MAX_EMBED_CHARS_PER_MESSAGE
        ):
            messages.append({"embeds": current})
            current, size = [], 0
        current.append(embed)
        size += embed_size(embed)
    messages.append({"embeds": current})
    messages[0]["content"] = header
    return messages


def post(webhook_url, message, username):
    payload = {"username": username, "allowed_mentions": {"parse": []}, **message}
    request = urllib.request.Request(
        webhook_url + ("&" if "?" in webhook_url else "?") + "wait=true",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
        method="POST",
    )
    for attempt in range(1, 4):
        try:
            with urllib.request.urlopen(request, timeout=30):
                return
        except urllib.error.HTTPError as error:
            if error.code != 429 or attempt == 3:
                detail = error.read().decode(errors="replace")
                raise SystemExit(f"Discord webhook returned {error.code}: {detail}") from error
            retry_after = json.loads(error.read() or b"{}").get("retry_after", 2)
            time.sleep(float(retry_after) + 0.5)


def main():
    load_dotenv(Path(__file__).with_name(".env"))

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--date", type=dt.date.fromisoformat, help="YYYY-MM-DD (default: today)")
    parser.add_argument("--dry-run", action="store_true", help="print the payloads instead of posting")
    args = parser.parse_args()

    timezone = ZoneInfo(os.environ.get("READINGS_TIMEZONE", "America/Chicago"))
    date = args.date or dt.datetime.now(timezone).date()
    messages = build_messages(fetch_day(date))

    if args.dry_run:
        print(json.dumps(messages, indent=2, ensure_ascii=False))
        return

    webhook_url = os.environ.get("DISCORD_WEBHOOK_URL")
    if not webhook_url:
        sys.exit("DISCORD_WEBHOOK_URL is not set. Add it to .env or the environment.")
    username = os.environ.get("BOT_USERNAME", "Daily Readings")
    for message in messages:
        post(webhook_url, message, username)
    print(f"Posted {len(messages)} message(s) for {date.isoformat()}.")


if __name__ == "__main__":
    main()
