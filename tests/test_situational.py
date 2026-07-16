from __future__ import annotations

import json
import unittest

from jakasii_ops.situational import OperationalSnapshotEngine


class SituationalAwarenessTests(unittest.TestCase):
    def test_snapshot_reports_coverage_without_copying_evidence_payloads(self) -> None:
        evidence = [
            {
                "id": "obs-1",
                "kind": "observation",
                "source": "camera",
                "occurred_at": "2026-07-16T10:00:00+05:30",
                "payload": {"private_frame": "never-copy-this"},
            },
            {
                "id": "sys-1",
                "kind": "system_record",
                "source": "pos",
                "occurred_at": "2026-07-16T10:05:00+05:30",
                "payload": {"private_customer": "never-copy-this"},
            },
            {
                "id": "sys-2",
                "kind": "system_record",
                "source": "purchase",
                "occurred_at": "2026-07-16T12:00:00+05:30",
                "payload": {"private_supplier": "never-copy-this"},
            },
        ]
        snapshot = OperationalSnapshotEngine(15).build(
            "shop_1",
            {"ready": False, "unresolved_questions": 2},
            evidence,
            [{"event_type": "sale", "status": "needs_verification"}],
            [{"role": "manager", "status": "open"}],
        )

        self.assertEqual(1, snapshot["correlation"]["corroborated_system_records"])
        self.assertEqual(1, snapshot["correlation"]["uncorroborated_system_records"])
        self.assertEqual("temporal_cooccurrence_only", snapshot["correlation"]["matches"][0]["claim"])
        self.assertEqual({"manager": 1}, snapshot["open_tasks_by_role"])
        self.assertEqual("needs_attention", snapshot["state"])
        self.assertNotIn("never-copy-this", json.dumps(snapshot))


if __name__ == "__main__":
    unittest.main()
