import unittest

import common


class HtmlToTextTest(unittest.TestCase):
    def test_paragraphs_breaks_and_entities(self):
        html = "<p>In the  beginning &amp; the\n end.</p><p>Line one<br>Line two</p>"
        self.assertEqual(
            common.html_to_text(html),
            "In the beginning & the end.\n\nLine one\nLine two",
        )

    def test_italics_hug_the_text(self):
        html = "<p><em> The Feast is kept on October 1.</em> See <i>Patrologia Graeca</i>.</p>"
        self.assertEqual(
            common.html_to_text(html),
            "*The Feast is kept on October 1.* See *Patrologia Graeca*.",
        )

    def test_italics_across_paragraphs_are_dropped(self):
        self.assertEqual(common.html_to_text("<p><i>One</p><p>Two</i></p>"), "One\n\nTwo")

    def test_markdown_characters_are_escaped(self):
        hymn = "All the powers of Heaven * were amazed * at the_deeds"
        self.assertEqual(
            common.html_to_text(hymn),
            r"All the powers of Heaven \* were amazed \* at the\_deeds",
        )

    def test_superscripts_join_their_word(self):
        html = "<p><span>born in the 14</span><sup><span>th</span></sup><span> century</span></p>"
        self.assertEqual(common.html_to_text(html), "born in the 14th century")


class SplitTextTest(unittest.TestCase):
    def test_short_text_is_one_chunk(self):
        self.assertEqual(common.split_text("Short.", 100), ["Short."])

    def test_prefers_paragraph_boundary(self):
        text = "a" * 60 + "\n\n" + "b" * 60
        self.assertEqual(common.split_text(text, 100), ["a" * 60, "b" * 60])

    def test_falls_back_to_sentence_boundary_keeping_closing_quote(self):
        text = 'He said, "' + "x" * 60 + '." Then ' + "y" * 60
        chunks = common.split_text(text, 100)
        self.assertTrue(chunks[0].endswith('."'))
        self.assertTrue(chunks[1].startswith("Then"))

    def test_chunks_respect_limit_and_keep_all_words(self):
        text = " ".join(["word"] * 5000)
        chunks = common.split_text(text, common.MAX_DESCRIPTION)
        self.assertTrue(all(len(chunk) <= common.MAX_DESCRIPTION for chunk in chunks))
        self.assertEqual(" ".join(chunks), text)


class PackEmbedsTest(unittest.TestCase):
    def test_starts_a_new_message_at_ten_embeds(self):
        embeds = [{"description": "x"} for _ in range(11)]
        messages = common.pack_embeds(embeds, "header")

        self.assertEqual([len(m["embeds"]) for m in messages], [10, 1])
        self.assertEqual(messages[0]["content"], "header")
        self.assertNotIn("content", messages[1])

    def test_starts_a_new_message_before_the_character_limit(self):
        embeds = [{"description": "x" * 4000} for _ in range(2)]
        self.assertEqual(len(common.pack_embeds(embeds, "header")), 2)


if __name__ == "__main__":
    unittest.main()
