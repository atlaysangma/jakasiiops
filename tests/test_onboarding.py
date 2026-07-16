from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jakasii_ops.brain import JakasiiOpsBrain
from jakasii_ops.onboarding import MappingEngine


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
        rescanned = self.brain.onboard(fixture / "schema.json")
        self.assertEqual([], rescanned["questions"])
        self.assertTrue(rescanned["readiness"]["ready"])
        memory = self.brain.memory(result["profile"]["store_id"])
        self.assertIn("Store.md", memory)
        self.assertIn("Learning/Readiness.md", memory)

    def test_destination_mapping_prefers_to_over_from_or_form(self) -> None:
        document = {
            "store_id": "direction_shop",
            "name": "Direction Shop",
            "sources": [
                {
                    "name": "legacy",
                    "tables": [
                        {
                            "name": "StockTransfer",
                            "columns": [
                                {"name": "GoDownForm", "type": "int"},
                                {"name": "GoDownTo", "type": "int"},
                            ],
                        }
                    ],
                }
            ],
        }
        mapping = next(
            item
            for item in MappingEngine().propose(document)
            if item.canonical_field == "movement.destination"
        )
        self.assertTrue(mapping.source_path.endswith("GoDownTo"))

    def test_authorized_semantic_contracts_need_no_human_confirmation(self) -> None:
        document = json.loads(
            (ROOT / "fixtures/modern_shop/schema.json").read_text(encoding="utf-8")
        )
        source = document["sources"][0]
        source["semantic_contracts"] = [
            {
                "canonical_field": "camera.zone",
                "table": "camera_channels",
                "column": "camera_zone",
                "authority": "authorized_connector_contract",
            },
            {
                "canonical_field": "staff.role",
                "table": "staff",
                "column": "staff_role",
                "authority": "authorized_connector_contract",
            },
        ]
        document["requires_mapping_confirmation"] = True

        class Connector:
            def inspect_schema(self):
                return document

        result = self.brain.onboard_connector(Connector())
        question_keys = {item["key"] for item in result["questions"]}
        mappings = {
            item["canonical_field"]: item for item in result["profile"]["mappings"]
        }
        catalog = self.brain.schema_catalog(document["store_id"])

        self.assertNotIn("verify:camera.zone", question_keys)
        self.assertNotIn("verify:staff.role", question_keys)
        self.assertTrue(mappings["camera.zone"]["verified"])
        self.assertTrue(mappings["staff.role"]["verified"])
        self.assertEqual(2, len(catalog["sources"][0]["semantic_contracts"]))
        self.assertNotIn(
            "staff_directory", self.brain.awareness(document["store_id"])["unknowns"]
        )


if __name__ == "__main__":
    unittest.main()
