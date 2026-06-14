import unittest
from datetime import date

from core import (
    achievements_for,
    choose_task,
    make_daily_state,
    parse_group_characters,
    parse_health_endpoints,
)


class CoreTests(unittest.TestCase):
    def test_daily_state_is_stable(self):
        first = make_daily_state(date(2026, 6, 14), "user-1", "李子")
        second = make_daily_state(date(2026, 6, 14), "user-1", "李子")
        self.assertEqual(first, second)
        self.assertGreaterEqual(first.missing_you, 65)

    def test_task_is_stable_and_nonempty(self):
        task = choose_task(["喝水", "洗脸"], date(2026, 6, 14), "u", 1)
        self.assertIn(task["content"], {"喝水", "洗脸"})
        self.assertGreater(task["minutes"], 0)

    def test_parsers_ignore_bad_lines(self):
        self.assertEqual(
            parse_group_characters("李子|嘴硬\n坏行"),
            [("李子", "嘴硬")],
        )
        self.assertEqual(
            parse_health_endpoints("Embedding|https://x/health|abc\nbad"),
            [("Embedding", "https://x/health", "abc")],
        )

    def test_achievements(self):
        items = achievements_for(
            {
                "completed_count": 10,
                "diary_count": 1,
                "checked_server": True,
            }
        )
        self.assertEqual(len(items), 5)


if __name__ == "__main__":
    unittest.main()
