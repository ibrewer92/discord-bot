import datetime as dt
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import common
import run_daily

TODAY = dt.date(2026, 10, 13)


class FakeBot:
    def __init__(self, name, results):
        self.name = name
        self.results = list(results)  # each: a message count, or an exception to raise
        self.calls = 0

    def post(self, date):
        self.calls += 1
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class RunDailyTest(unittest.TestCase):
    def setUp(self):
        tmp = Path(tempfile.mkdtemp())
        for name, value in (("STATE_DIR", tmp / "state"), ("LOG_FILE", tmp / "logs" / "daily.log")):
            patcher = mock.patch.object(run_daily, name, value)
            patcher.start()
            self.addCleanup(patcher.stop)
        self.sleep = mock.patch.object(run_daily.time, "sleep").start()
        self.addCleanup(mock.patch.stopall)
        mock.patch.object(run_daily.common, "today", return_value=TODAY).start()
        mock.patch.object(run_daily.common, "load_env").start()
        mock.patch.object(run_daily.sys, "argv", ["run_daily.py"]).start()

    def use_bots(self, *bots):
        mock.patch.object(run_daily, "BOTS", list(bots)).start()

    def test_posts_each_bot_once_and_marks_it(self):
        readings, saints = FakeBot("readings", [2]), FakeBot("saints", [0])
        self.use_bots(readings, saints)

        self.assertEqual(run_daily.main(), 0)
        self.assertTrue(run_daily.marker(readings, TODAY).exists())
        self.assertTrue(run_daily.marker(saints, TODAY).exists())

        # A second run the same day posts nothing.
        self.assertEqual(run_daily.main(), 0)
        self.assertEqual((readings.calls, saints.calls), (1, 1))
        self.sleep.assert_not_called()
        log = run_daily.LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("readings: posted 2 message(s) for 2026-10-13", log)
        self.assertIn("saints: nothing to post for 2026-10-13", log)
        self.assertIn("readings: already posted for 2026-10-13", log)

    def test_retries_only_what_failed(self):
        readings = FakeBot("readings", [1])
        saints = FakeBot("saints", [common.PostError("Discord webhook returned 503"), OSError("offline"), 1])
        self.use_bots(readings, saints)

        self.assertEqual(run_daily.main(), 0)
        self.assertEqual((readings.calls, saints.calls), (1, 3))
        self.assertEqual(self.sleep.call_count, 2)
        self.assertIn("saints: failed: PostError: Discord webhook returned 503", run_daily.LOG_FILE.read_text(encoding="utf-8"))

    def test_gives_up_after_the_last_attempt_without_marking(self):
        saints = FakeBot("saints", [OSError("offline")] * run_daily.ATTEMPTS)
        self.use_bots(saints)

        self.assertEqual(run_daily.main(), 1)
        self.assertEqual(saints.calls, run_daily.ATTEMPTS)
        self.assertEqual(self.sleep.call_count, run_daily.ATTEMPTS - 1)
        self.assertFalse(run_daily.marker(saints, TODAY).exists())
        self.assertIn("Gave up on: saints", run_daily.LOG_FILE.read_text(encoding="utf-8"))

    def test_prunes_markers_older_than_30_days(self):
        bot = FakeBot("readings", [])
        run_daily.STATE_DIR.mkdir(parents=True)
        old, recent = run_daily.marker(bot, TODAY - dt.timedelta(days=31)), run_daily.marker(bot, TODAY - dt.timedelta(days=30))
        old.touch()
        recent.touch()

        run_daily.prune_markers(TODAY)

        self.assertFalse(old.exists())
        self.assertTrue(recent.exists())

    def test_dry_run_reports_a_missing_webhook_and_posts_nothing(self):
        set_bot = common.Bot("readings", "", lambda date: [{"content": "x"}], "SET_WEBHOOK", "U", "u")
        unset_bot = common.Bot("saints", "", lambda date: [], "UNSET_WEBHOOK", "U", "u")
        self.use_bots(set_bot, unset_bot)
        mock.patch.object(run_daily.sys, "argv", ["run_daily.py", "--dry-run"]).start()
        mock.patch.dict(run_daily.common.os.environ, {"SET_WEBHOOK": "https://example.test/hook"}).start()
        post = mock.patch.object(common, "post").start()

        self.assertEqual(run_daily.main(), 1)
        post.assert_not_called()
        log = run_daily.LOG_FILE.read_text(encoding="utf-8")
        self.assertIn("readings: 1 message(s) ready for 2026-10-13", log)
        self.assertIn("saints: UNSET_WEBHOOK is not set", log)
        self.assertIn("saints: 0 message(s) ready for 2026-10-13", log)  # feed still checked
        self.assertIn("Setup check failed.", log)


class LoadDotenvTest(unittest.TestCase):
    def test_reads_a_file_saved_with_a_byte_order_mark(self):
        path = Path(tempfile.mkdtemp()) / ".env"
        path.write_text("﻿BOM_TEST_WEBHOOK=https://example.test/hook\n", encoding="utf-8")
        with mock.patch.dict(common.os.environ, {}, clear=False):
            common.load_dotenv(path)
            self.assertEqual(common.os.environ.get("BOM_TEST_WEBHOOK"), "https://example.test/hook")


if __name__ == "__main__":
    unittest.main()
