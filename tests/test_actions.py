from __future__ import annotations

import tempfile
import unittest

from jakasii_ops.brain import JakasiiOpsBrain


class ActionPolicyTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.brain = JakasiiOpsBrain(self.temp.name)

    def tearDown(self) -> None:
        self.brain.close()
        self.temp.cleanup()

    def test_local_memory_is_allowed_but_official_record_waits(self) -> None:
        local = self.brain.request_action(
            "store", "write_memory", "store-memory/Store.md", "Save verified mapping", "local_work"
        )
        official = self.brain.request_action(
            "store", "adjust_stock", "pos.stock", "Apply confirmed variance", "official_record"
        )
        self.assertEqual("allowed", local["status"])
        self.assertEqual("pending_approval", official["status"])

    def test_prohibited_action_cannot_be_approved(self) -> None:
        request = self.brain.request_action(
            "store", "extract_credentials", "system", "Discover secret", "prohibited"
        )
        self.assertEqual("denied", request["status"])
        with self.assertRaises(PermissionError):
            self.brain.approve_action("store", request["id"], "owner")


if __name__ == "__main__":
    unittest.main()

