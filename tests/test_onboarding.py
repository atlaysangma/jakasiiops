from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jakasii_ops.brain import JakasiiOpsBrain


ROOT = Path(__file__).resolve().parents[1]


class OnboardingTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.brain = JakasiiOpsBrain(self.temp.name)

    def tearDown(self) -> None:
        self.brain.close()
        self.temp.cleanup()

    def test_modern_schema_is_inferred_without_questions(self) -> None:
        result = self.brain.onboard(ROOT / "fixtures/modern_shop/schema.json")
        self.assertEqual([], result["questions"])
        self.assertTrue(result["readiness"]["ready"])
        self.assertEqual(5, sum(check["passed"] for check in result["readiness"]["checks"]))

    def test_messy_schema_asks_then_becomes_ready(self) -> None:
        fixture = ROOT / "fixtures/legacy_mart"
        result = self.brain.onboard(fixture / "schema.json")
        self.assertGreaterEqual(len(result["questions"]), 4)
        self.assertFalse(result["readiness"]["ready"])
        answers = json.loads((fixture / "answers.json").read_text(encoding="utf-8"))
        for question in result["questions"]:
            self.brain.answer_setup(
                result["profile"]["store_id"], question["id"], answers[question["key"]], "test_owner"
            )
        readiness = self.brain.readiness(result["profile"]["store_id"])
        self.assertTrue(readiness["ready"])
        memory = self.brain.memory(result["profile"]["store_id"])
        self.assertIn("Store.md", memory)
        self.assertIn("Learning/Readiness.md", memory)


if __name__ == "__main__":
    unittest.main()

