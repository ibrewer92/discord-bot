import unittest
import xml.etree.ElementTree as ET
from xml.sax.saxutils import escape
from datetime import date
from unittest import mock

import common
import post_saints as ps


def daily_feed(*entries):
    """entries: (id, title, classification)"""
    items = "".join(
        f"""<saintfeast><title>{escape(title)}</title><id>{id_}</id>
            <publicurl>http://www.goarch.org/chapel/saints?contentid={id_}</publicurl>
            <classification>{rank}</classification></saintfeast>"""
        for id_, title, rank in entries
    )
    return ET.fromstring(f"<onlinechapel><saintsfeasts>{items}</saintsfeasts></onlinechapel>")


def saint_detail(life="", icon="small/allsaint.jpg", hymns=()):
    life_xml = (
        f"""<translation xml:lang="en"><title>Reading</title>
            <body><![CDATA[{life}]]></body>
            <copyright>Holy Transfiguration Monastery - Brookline, MA</copyright></translation>"""
        if life
        else ""
    )
    hymn_xml = "".join(
        f"""<hymn><type>{kind}</type><tone>{tone}</tone>
            <translation xml:lang="en"><body>{text}</body>
            <copyright>Holy Transfiguration Monastery</copyright></translation></hymn>"""
        for kind, tone, text in hymns
    )
    return ET.fromstring(
        f"""<saintfeast><icons><icon id="1"><filepath>{icon}</filepath>
            <url>http://onlinechapel.goarch.org/images/{icon}</url>
            <copyright>St. Isaac of Syria Skete</copyright></icon></icons>
            <readings>{life_xml}</readings><hymns>{hymn_xml}</hymns></saintfeast>"""
    )


class FetchSaintsTest(unittest.TestCase):
    def fetch(self, feed, details):
        with (
            mock.patch.object(ps, "daily_feed", return_value=feed),
            mock.patch.object(ps, "fetch_xml", side_effect=lambda url: details[url.rsplit("=", 1)[1]]),
        ):
            return ps.fetch_saints(date(2026, 10, 12))

    def test_keeps_only_entries_with_a_life_greatest_feast_first(self):
        feed = daily_feed(
            ("1", "Probus, Andronicus, & Tarachus", "10"),
            ("2", "Symeon the New Theologian", "8"),
            ("3", "Cosmas the Hymnographer", "10"),
            ("4", "6th Sunday of Luke", "5"),
            ("5", "Domnina the Martyr", "10"),
        )
        details = {
            "1": saint_detail("<p>The holy Martyrs contested for Christ.</p>"),
            "2": saint_detail("<p>Saint Symeon became a monk.</p>"),
            "3": saint_detail(),  # no life at all
            "4": saint_detail(hymns=[("apolytikion", "Plagal of the First Tone", "Hymn only.")]),
            "5": saint_detail("<p>Domnina was martyred.</p>"),
        }
        day = self.fetch(feed, details)

        self.assertEqual(day["formatted_date"], "Monday, October 12, 2026")
        self.assertEqual(
            [s["name"] for s in day["saints"]],
            ["Symeon the New Theologian", "Probus, Andronicus, & Tarachus", "Domnina the Martyr"],
        )
        self.assertEqual(day["saints"][0]["link"], "https://www.goarch.org/chapel/saints?contentid=2")

    def test_uses_own_icon_but_not_the_placeholder(self):
        feed = daily_feed(("1", "Symeon", "8"), ("2", "Probus", "10"))
        details = {
            "1": saint_detail("<p>Life.</p>", icon="skete/symeonnewspious.jpg"),
            "2": saint_detail("<p>Life.</p>"),
        }
        symeon, probus = self.fetch(feed, details)["saints"]

        self.assertEqual(symeon["icon_url"], "https://onlinechapel.goarch.org/images/skete/symeonnewspious.jpg")
        self.assertEqual(symeon["icon_copyright"], "St. Isaac of Syria Skete")
        self.assertIsNone(probus["icon_url"])
        self.assertIsNone(probus["icon_copyright"])

    def test_reads_hymns_with_their_tones(self):
        feed = daily_feed(("1", "Symeon", "8"))
        details = {
            "1": saint_detail(
                "<p>Life.</p>",
                hymns=[("apolytikion", "Third Tone", "Since thou hadst received * God's enlightenment"),
                       ("kontakion", "", "Shining with the Three-Sun Light")],
            )
        }
        (symeon,) = self.fetch(feed, details)["saints"]

        self.assertEqual(
            [(h["type"], h["tone"], h["text"]) for h in symeon["hymns"]],
            [
                ("Apolytikion", "Third Tone", r"Since thou hadst received \* God's enlightenment"),
                ("Kontakion", "", "Shining with the Three-Sun Light"),
            ],
        )


def saint(name="Symeon the New Theologian", life="Saint Symeon became a monk.", icon=True, hymns=None):
    return {
        "name": name,
        "link": "https://www.goarch.org/chapel/saints?contentid=1180",
        "rank": 8,
        "life": life,
        "life_copyright": "Holy Transfiguration Monastery - Brookline, MA",
        "icon_url": "https://onlinechapel.goarch.org/images/skete/symeonnewspious.jpg" if icon else None,
        "icon_copyright": "St. Isaac of Syria Skete" if icon else None,
        "hymns": hymns
        if hymns is not None
        else [
            {"type": "Apolytikion", "tone": "Third Tone", "text": "Since thou hadst received", "copyright": "Holy Transfiguration Monastery"},
            {"type": "Kontakion", "tone": "Third Tone", "text": "Shining with the Three-Sun Light", "copyright": "Holy Transfiguration Monastery"},
        ],
    }


class BuildMessagesTest(unittest.TestCase):
    def test_one_embed_per_saint_with_life_hymns_icon_and_credits(self):
        day = {"formatted_date": "Monday, October 12, 2026", "saints": [saint(), saint("Probus", icon=False, hymns=[])]}
        (message,) = ps.build_messages(day)

        self.assertEqual(message["content"], "**Monday, October 12, 2026**")
        symeon, probus = message["embeds"]
        self.assertEqual(symeon["title"], "Symeon the New Theologian")
        self.assertEqual(symeon["url"], "https://www.goarch.org/chapel/saints?contentid=1180")
        self.assertEqual(symeon["thumbnail"], {"url": "https://onlinechapel.goarch.org/images/skete/symeonnewspious.jpg"})
        self.assertEqual(
            symeon["description"],
            "Saint Symeon became a monk.\n\n"
            "**Apolytikion (Third Tone)**\nSince thou hadst received\n\n"
            "**Kontakion (Third Tone)**\nShining with the Three-Sun Light",
        )
        self.assertEqual(
            symeon["footer"]["text"],
            "Life: Holy Transfiguration Monastery - Brookline, MA · Hymns: Holy Transfiguration Monastery"
            " · Icon: St. Isaac of Syria Skete",
        )
        self.assertNotIn("thumbnail", probus)
        self.assertEqual(probus["description"], "Saint Symeon became a monk.")
        self.assertEqual(probus["footer"]["text"], "Life: Holy Transfiguration Monastery - Brookline, MA")

    def test_long_life_continues_in_more_embeds_with_credits_on_the_last(self):
        long_life = "\n\n".join(["The saint lived and taught. " * 100] * 3)  # about 8,000 chars
        messages = ps.build_messages({"formatted_date": "Saturday, August 15, 2026", "saints": [saint(life=long_life)]})

        embeds = [e for m in messages for e in m["embeds"]]
        self.assertGreater(len(embeds), 1)
        self.assertTrue(all(len(e["description"]) <= common.MAX_DESCRIPTION for e in embeds))
        self.assertEqual(embeds[0]["title"], "Symeon the New Theologian")
        self.assertTrue(all(e["author"]["name"] == "Symeon the New Theologian (continued)" for e in embeds[1:]))
        self.assertTrue(all("footer" not in e for e in embeds[:-1]))
        self.assertIn("footer", embeds[-1])
        self.assertTrue(embeds[-1]["description"].endswith("Shining with the Three-Sun Light"))

    def test_nothing_to_post_without_saints(self):
        self.assertEqual(ps.build_messages({"formatted_date": "Tuesday, March 16, 2027", "saints": []}), [])


if __name__ == "__main__":
    unittest.main()
