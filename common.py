"""Shared pieces for the bots: the GOA Online Chapel feed, HTML-to-Discord
text conversion, embed splitting and packing, and webhook posting."""

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
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Callable
from zoneinfo import ZoneInfo

DAILY_FEED_URL = "https://onlinechapel.goarch.org/daily.asp?date={date:%m/%d/%Y}"
USER_AGENT = "discord-lectionary-bot/1.0 (personal use)"
XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"

# Discord embed limits: https://discord.com/developers/docs/resources/message#embed-object-embed-limits
MAX_TITLE = 256
MAX_DESCRIPTION = 4096
MAX_FOOTER = 2048
MAX_EMBEDS_PER_MESSAGE = 10
MAX_EMBED_CHARS_PER_MESSAGE = 6000


def load_dotenv(path):
    if not path.exists():
        return
    # utf-8-sig also reads files Windows Notepad saved with a byte-order mark.
    for line in path.read_text(encoding="utf-8-sig").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def load_env():
    load_dotenv(Path(__file__).with_name(".env"))


def today():
    return dt.datetime.now(ZoneInfo(os.environ.get("BOT_TIMEZONE", "America/Chicago"))).date()


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


def daily_feed(date):
    return fetch_xml(DAILY_FEED_URL.format(date=date))


def format_date(date):
    # The feed's own formatteddate zero-pads some days ("May 02").
    return f"{date:%A, %B} {date.day}, {date:%Y}"


def https(url):
    return re.sub(r"^http://", "https://", url or "")


def english(element):
    if element is None:
        return None
    for translation in element.findall("translation"):
        if translation.get(XML_LANG) == "en":
            return translation
    return None


MARKDOWN_SPECIAL = re.compile(r"([\\*_~`|])")
ITALIC_OPEN, ITALIC_CLOSE = "", ""
ITALIC_SPAN = re.compile(f"{ITALIC_OPEN}(\\s*)([^{ITALIC_OPEN}{ITALIC_CLOSE}\n]*?)(\\s*){ITALIC_CLOSE}")


def escape_markdown(text):
    return MARKDOWN_SPECIAL.sub(r"\\\1", text)


class _TextExtractor(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag == "br":
            self.parts.append("\n")
        elif tag in ("i", "em"):
            self.parts.append(ITALIC_OPEN)

    def handle_endtag(self, tag):
        if tag == "p":
            self.parts.append("\n\n")
        elif tag in ("i", "em"):
            self.parts.append(ITALIC_CLOSE)

    def handle_data(self, data):
        # Newlines in HTML source are just whitespace; only <p> and <br> break lines.
        self.parts.append(escape_markdown(re.sub(r"\s+", " ", data)))


def _italicize(match):
    lead, inner, trail = match.groups()
    # Discord only italicizes when the asterisks touch the text.
    return f"{lead}*{inner}*{trail}" if inner else lead + trail


def html_to_text(html):
    """Convert feed HTML to Discord markdown: paragraphs, line breaks, and italics."""
    extractor = _TextExtractor()
    extractor.feed(html or "")
    text = ITALIC_SPAN.sub(_italicize, "".join(extractor.parts))
    text = text.replace(ITALIC_OPEN, "").replace(ITALIC_CLOSE, "")
    paragraphs = []
    for paragraph in re.split(r"\n\s*\n", text):
        lines = [" ".join(line.split()) for line in paragraph.split("\n")]
        paragraph = "\n".join(line for line in lines if line)
        if paragraph:
            paragraphs.append(paragraph)
    return "\n\n".join(paragraphs)


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


def text_embeds(text, color, first, continued_author):
    """Spread text over as many embeds as it needs. The first embed also gets
    the `first` fields (title, url, author, thumbnail); later ones are labelled
    with `continued_author`."""
    embeds = []
    for index, chunk in enumerate(split_text(text, MAX_DESCRIPTION)):
        embed = {"color": color, "description": chunk}
        embed.update(first if index == 0 else {"author": {"name": continued_author[:MAX_TITLE]}})
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


def pack_embeds(embeds, content):
    """Group embeds into as few messages as Discord's limits allow. `content`
    goes on the first message."""
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
    messages[0]["content"] = content
    return messages


class PostError(Exception):
    """A webhook post failed, or a webhook URL isn't set."""


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
                raise PostError(f"Discord webhook returned {error.code}: {detail}") from error
            retry_after = json.loads(error.read() or b"{}").get("retry_after", 2)
            time.sleep(float(retry_after) + 0.5)


@dataclass(frozen=True)
class Bot:
    """One daily post: how to build its messages and where to send them."""

    name: str
    description: str
    build_messages_for: Callable[[dt.date], list]
    webhook_env: str
    username_env: str
    default_username: str

    def webhook_url(self):
        url = os.environ.get(self.webhook_env)
        if not url:
            raise PostError(f"{self.webhook_env} is not set. Add it to .env or the environment.")
        return url

    def post(self, date):
        """Build and post the messages for `date`. Returns how many were posted."""
        messages = self.build_messages_for(date)
        if not messages:
            return 0
        webhook_url = self.webhook_url()
        username = os.environ.get(self.username_env, self.default_username)
        for message in messages:
            post(webhook_url, message, username)
        return len(messages)


def run(bot):
    """Command-line entry point for one bot: work out the date, then print
    the messages (--dry-run) or post them."""
    load_env()

    parser = argparse.ArgumentParser(description=bot.description)
    parser.add_argument(
        "--date",
        type=lambda value: dt.date.fromisoformat(value) if value else None,
        help="YYYY-MM-DD (default: today)",
    )
    parser.add_argument("--dry-run", action="store_true", help="print the payloads instead of posting")
    args = parser.parse_args()

    date = args.date or today()
    if args.dry_run:
        print(json.dumps(bot.build_messages_for(date), indent=2, ensure_ascii=False))
        return
    try:
        count = bot.post(date)
    except PostError as error:
        sys.exit(str(error))
    if count:
        print(f"Posted {count} message(s) for {date.isoformat()}.")
    else:
        print(f"Nothing to post for {date.isoformat()}.")
