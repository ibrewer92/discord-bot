import unittest
import xml.etree.ElementTree as ET
from datetime import date
from unittest import mock

import post_readings as pr


def reading(kind, text, prokeimenon=None):
    return {
        "kind": kind,
        "label": pr.READING_TYPES[kind],
        "title": f"{kind} title",
        "link": "https://example.test",
        "prokeimenon": prokeimenon,
        "text": text,
    }


class HtmlToTextTest(unittest.TestCase):
    def test_paragraphs_breaks_and_entities(self):
        html = "<p>In the  beginning &amp; the\n end.</p><p>Line one<br>Line two</p>"
        self.assertEqual(
            pr.html_to_text(html),
            "In the beginning & the end.\n\nLine one\nLine two",
        )


class SplitTextTest(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(pr.split_text("Short.", 100), ["Short."])

    def test_prefers_paragraph_boundary(self):
        text = "a" * 60 + "\n\n" + "b" * 60
        self.assertEqual(pr.split_text(text, 100), ["a" * 60, "b" * 60])

    def test_falls_back_to_sentence_boundary_keeping_closing_quote(self):
        text = 'He said, "' + "x" * 60 + '." Then ' + "y" * 60
        chunks = pr.split_text(text, 100)
        self.assertTrue(chunks[0].endswith('."'))
        self.assertTrue(chunks[1].startswith("Then"))

    def test_chunks_respect_limit_and_keep_all_words(self):
        text = " ".join(["word"] * 5000)
        chunks = pr.split_text(text, pr.MAX_DESCRIPTION)
        self.assertTrue(all(len(chunk) <= pr.MAX_DESCRIPTION for chunk in chunks))
        self.assertEqual(" ".join(chunks), text)


class BuildMessagesTest(unittest.TestCase):
    def day(self, readings, others=()):
        return {
            "formatted_date": "Monday, October 12, 2026",
            "lectionary_title": "Monday of the 4th Week",
            "readings": readings,
            "others": list(others),
        }

    def test_epistle_and_gospel_in_one_message(self):
        prokeimenon = {"mode": "4", "text": "Who makes his angels spirits", "verse": "Verse: Bless the Lord"}
        messages = pr.build_messages(self.day([reading("E", "Brethren.", prokeimenon), reading("G", "At that time.")]))

        self.assertEqual(len(messages), 1)
        self.assertEqual(messages[0]["content"], "**Monday, October 12, 2026**\nMonday of the 4th Week")
        epistle, gospel = messages[0]["embeds"]
        self.assertEqual(epistle["author"]["name"], "Epistle")
        self.assertTrue(epistle["description"].startswith("*Prokeimenon (Mode 4):* Who makes his angels spirits"))
        self.assertTrue(epistle["description"].endswith("Brethren."))
        self.assertEqual(gospel["author"]["name"], "Gospel")
        self.assertEqual(gospel["footer"]["text"], pr.FOOTER)
        self.assertNotIn("footer", epistle)

    def test_long_reading_splits_across_messages_within_limits(self):
        long_text = "\n\n".join(["Verse text here. " * 200] * 3)  # about 10,000 chars, like Holy Thursday
        messages = pr.build_messages(self.day([reading("E", "Short epistle."), reading("G", long_text)]))

        self.assertGreater(len(messages), 1)
        for message in messages:
            self.assertLessEqual(len(message["embeds"]), pr.MAX_EMBEDS_PER_MESSAGE)
            self.assertLessEqual(sum(map(pr.embed_size, message["embeds"])), pr.MAX_EMBED_CHARS_PER_MESSAGE)
            for embed in message["embeds"]:
                self.assertLessEqual(len(embed["description"]), pr.MAX_DESCRIPTION)
        continued = [e for m in messages for e in m["embeds"] if e["author"]["name"] == "Gospel (continued)"]
        self.assertTrue(continued)
        self.assertTrue(all("title" not in e for e in continued))
        self.assertNotIn("content", messages[1])

    def test_day_without_epistle_or_gospel_lists_other_readings(self):
        others = [{"title": "Isaiah 1:19-2:3", "link": "https://example.test/isaiah"}]
        messages = pr.build_messages(self.day([], others))

        self.assertEqual(len(messages), 1)
        content = messages[0]["content"]
        self.assertIn("No Epistle or Gospel is appointed for today.", content)
        self.assertIn("- [Isaiah 1:19-2:3](<https://example.test/isaiah>)", content)
        self.assertNotIn("embeds", messages[0])


def daily_feed(eothinon, *kinds):
    readings = "".join(
        f"""<reading><type>{kind}</type>
            <url>http://onlinechapel.goarch.org/lectionary.asp?type={kind}</url>
            <publicurl>http://www.goarch.org/chapel/lectionary?type={kind}</publicurl>
            <translation xml:lang="en"><title>{kind} listing</title></translation>
        </reading>"""
        for kind in kinds
    )
    return f"""<onlinechapel><eothinon>{eothinon}</eothinon><readings>{readings}</readings>
        <lectionarytitle>Some Day</lectionarytitle></onlinechapel>"""


def full_reading(url):
    kind = url.rsplit("=", 1)[1]
    return ET.fromstring(
        f"""<onlinechapel><translation xml:lang="en"><title>{kind} full title</title>
            <body>&lt;p&gt;{kind} text.&lt;/p&gt;</body></translation></onlinechapel>"""
    )


class FetchDayTest(unittest.TestCase):
    def fetch(self, day, feed):
        def fake_fetch_xml(url):
            return ET.fromstring(feed) if "daily.asp" in url else full_reading(url)

        with mock.patch.object(pr, "fetch_xml", side_effect=fake_fetch_xml):
            return pr.fetch_day(day)

    def test_sunday_posts_matins_gospel_first_with_eothinon(self):
        result = self.fetch(date(2026, 10, 11), daily_feed("8", "MG", "E", "G"))

        self.assertEqual(
            [(r["kind"], r["label"], r["text"]) for r in result["readings"]],
            [
                ("MG", "Matins Gospel · Eothinon 8", "MG text."),
                ("E", "Epistle", "E text."),
                ("G", "Gospel", "G text."),
            ],
        )
        self.assertEqual(result["readings"][0]["link"], "https://www.goarch.org/chapel/lectionary?type=MG")

    def test_feast_posts_matins_gospel_without_eothinon(self):
        for eothinon in ("", "Festal"):  # weekday feast, feast on a Sunday
            with self.subTest(eothinon=eothinon):
                result = self.fetch(date(2027, 11, 21), daily_feed(eothinon, "MG", "E", "G"))

                self.assertEqual(
                    [(r["kind"], r["label"]) for r in result["readings"]],
                    [("MG", "Matins Gospel"), ("E", "Epistle"), ("G", "Gospel")],
                )

    def test_old_testament_readings_are_not_posted(self):
        result = self.fetch(date(2027, 3, 16), daily_feed("", "OT", "OT"))

        self.assertEqual(result["readings"], [])
        self.assertEqual(len(result["others"]), 2)


if __name__ == "__main__":
    unittest.main()
