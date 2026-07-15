from __future__ import annotations

import tempfile
import unittest

from jakasii_ops.brain import JakasiiOpsBrain


class WorkflowTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.brain = JakasiiOpsBrain(self.temp.name)
        self.store_id = "workflow_test_store"

    def tearDown(self) -> None:
        self.brain.close()
        self.temp.cleanup()

    def test_receiving_separates_evidence_and_routes_work(self) -> None:
        observed = self.brain.record_evidence(
            self.store_id, "observation", "camera", {"activity": "unloading"}, 0.7
        )
        recorded = self.brain.record_evidence(
            self.store_id, "system_record", "purchase_db", {"cartons": 1, "pack_size": 24}, 1.0
        )
        result = self.brain.process_event(
            self.store_id,
            "receiving",
            {
                "product_id": "SKU-1",
                "cartons": 1,
                "pack_size": 24,
                "destination_id": None,
                "receiver_confirmed": False,
            },
            [observed["id"], recorded["id"]],
        )
        roles = {task["role"] for task in result["tasks"]}
        self.assertEqual({"data_entry_operator", "godown_staff"}, roles)
        self.assertEqual("needs_verification", result["event"]["status"])
        evidence = self.brain.storage.list_records(self.store_id, "evidence")
        self.assertEqual({"observation", "system_record"}, {item["kind"] for item in evidence})

    def test_all_locked_operational_workflows_are_executable(self) -> None:
        cases = {
            "stock_movement": {"from_location": "GD-A", "to_location": "S-1", "sent_quantity": 10},
            "damage": {"product_id": "SKU-1", "quantity": 2},
            "attendance": {"source": "camera", "uniform": "blue"},
            "sale": {"product_id": "SKU-1", "quantity": 3, "stock_after": -1},
            "purchase": {"product_id": "SKU-1", "cartons": 2},
            "return": {"product_id": "SKU-1", "quantity": 1},
            "stock_count": {"product_id": "SKU-1", "expected_quantity": 20, "counted_quantity": 18},
            "expiry": {"product_id": "SKU-1", "quantity": 2}
        }
        for event_type, facts in cases.items():
            with self.subTest(event_type=event_type):
                result = self.brain.process_event(self.store_id, event_type, facts)
                self.assertGreaterEqual(len(result["tasks"]), 1)

    def test_human_task_answer_is_new_confirmation_evidence(self) -> None:
        result = self.brain.process_event(
            self.store_id, "damage", {"product_id": "SKU-1", "quantity": 2}
        )
        answered = self.brain.answer_task(
            self.store_id, result["tasks"][0]["id"], {"confirmed": True}, "manager-1"
        )
        self.assertEqual("answered", answered["status"])
        evidence = self.brain.storage.list_records(self.store_id, "evidence")
        self.assertEqual("human_confirmation", evidence[-1]["kind"])


if __name__ == "__main__":
    unittest.main()

