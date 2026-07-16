from __future__ import annotations

import json
import tempfile
import unittest

from jakasii_ops.brain import JakasiiOpsBrain


class OperationProofTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.brain = JakasiiOpsBrain(self.temp.name)
        self.store_id = "proof_shop"

    def tearDown(self) -> None:
        self.brain.close()
        self.temp.cleanup()

    def _receiving(self, camera_time: str, sql_time: str):
        camera = self.brain.record_evidence(
            self.store_id,
            "observation",
            "authorized_camera_collector",
            {"private_frame_path": "must-not-enter-proof"},
            0.8,
            occurred_at=camera_time,
        )
        system = self.brain.record_evidence(
            self.store_id,
            "system_record",
            "learned_sql_facts",
            {"private_product": "must-not-enter-proof"},
            1.0,
            occurred_at=sql_time,
        )
        return self.brain.process_event(
            self.store_id,
            "receiving",
            {
                "product_id": "SKU-PRIVATE",
                "pack_size": 12,
                "destination_id": "GD-PRIVATE",
                "receiver_confirmed": False,
            },
            [system["id"]],
            occurred_at=sql_time,
        )

    def test_timing_alone_never_completes_proof(self) -> None:
        event = self._receiving(
            "2026-07-16T10:00:00+00:00", "2026-07-16T10:02:00+00:00"
        )
        proof = self.brain.operation_proofs(self.store_id)["proofs"][0]

        self.assertEqual("awaiting_human_confirmation", proof["state"])
        self.assertFalse(proof["claims"]["camera_identified_product_or_quantity"])
        self.assertEqual([], proof["positive_confirmation_task_ids"])
        self.assertNotIn("SKU-PRIVATE", json.dumps(proof))
        self.assertEqual(event["event"]["id"], proof["event_id"])

    def test_positive_operational_confirmation_completes_evidence_bundle(self) -> None:
        event = self._receiving(
            "2026-07-16T10:00:00+00:00", "2026-07-16T10:02:00+00:00"
        )
        receiver_task = next(
            task for task in event["tasks"] if task["role"] == "godown_staff"
        )
        self.brain.answer_task(
            self.store_id,
            receiver_task["id"],
            {"confirmed": True},
            "authenticated-staff-gateway",
        )
        report = self.brain.operation_proofs(self.store_id)
        proof = report["proofs"][0]

        self.assertEqual("evidence_complete", proof["state"])
        self.assertEqual(1, report["complete_count"])
        self.assertTrue(proof["claims"]["database_record_present"])
        self.assertTrue(proof["claims"]["camera_temporal_context_present"])
        self.assertTrue(
            proof["claims"]["role_routed_human_confirmation_present"]
        )
        self.assertFalse(proof["claims"]["official_business_record_written_by_jakasii"])

    def test_negative_confirmation_disputes_operation(self) -> None:
        event = self._receiving(
            "2026-07-16T10:00:00+00:00", "2026-07-16T10:02:00+00:00"
        )
        receiver_task = next(
            task for task in event["tasks"] if task["role"] == "godown_staff"
        )
        self.brain.answer_task(
            self.store_id,
            receiver_task["id"],
            {"confirmed": False},
            "authenticated-staff-gateway",
        )
        proof = self.brain.operation_proofs(self.store_id)["proofs"][0]

        self.assertEqual("disputed", proof["state"])
        self.assertEqual([], proof["positive_confirmation_task_ids"])
        self.assertEqual([receiver_task["id"]], proof["negative_confirmation_task_ids"])

    def test_distant_camera_record_does_not_count(self) -> None:
        self._receiving(
            "2026-07-16T08:00:00+00:00", "2026-07-16T10:02:00+00:00"
        )
        proof = self.brain.operation_proofs(self.store_id)["proofs"][0]

        self.assertEqual("awaiting_camera_context", proof["state"])
        self.assertIsNone(proof["camera_observation_id"])


if __name__ == "__main__":
    unittest.main()
