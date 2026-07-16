from __future__ import annotations

import json
import tempfile
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

from jakasii_ops.api import OpsApiHandler
from jakasii_ops.brain import JakasiiOpsBrain


ROOT = Path(__file__).resolve().parents[1]


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.brain = JakasiiOpsBrain(self.temp.name)
        handler = type("ApiTestHandler", (OpsApiHandler,), {"brain": self.brain})
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.brain.close()
        self.temp.cleanup()

    def request(self, method: str, path: str, body: dict | None = None) -> dict:
        data = None if body is None else json.dumps(body).encode("utf-8")
        request = urllib.request.Request(
            self.base + path,
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(request) as response:
            return json.loads(response.read())

    def test_threaded_api_onboarding_and_operational_loop(self) -> None:
        onboard = self.request(
            "POST",
            "/onboarding",
            {"schema_path": str((ROOT / "fixtures/modern_shop/schema.json").resolve())},
        )
        self.assertTrue(onboard["readiness"]["ready"])
        store_id = onboard["profile"]["store_id"]
        schema = self.request("GET", f"/stores/{store_id}/schema")
        self.assertEqual(store_id, schema["store_id"])
        self.assertTrue(schema["sources"][0]["tables"])
        awareness = self.request("GET", f"/stores/{store_id}/awareness")
        self.assertEqual(store_id, awareness["store_id"])
        self.assertIn("product_catalog", awareness["capabilities_observed"])
        evidence = self.request(
            "POST",
            f"/stores/{store_id}/evidence",
            {
                "kind": "system_record",
                "source": "test-pos",
                "payload": {"product_id": "SKU-1", "quantity": 2},
            },
        )
        event = self.request(
            "POST",
            f"/stores/{store_id}/events",
            {
                "event_type": "receiving",
                "evidence_ids": [evidence["id"]],
                "facts": {
                    "product_id": "SKU-1",
                    "pack_size": 24,
                    "cartons": 1,
                    "destination_id": None,
                    "receiver_confirmed": False,
                },
            },
        )
        self.assertEqual(2, len(event["tasks"]))
        answered = self.request(
            "POST",
            f"/stores/{store_id}/tasks/{event['tasks'][0]['id']}/answer",
            {"actor": "deo-1", "answer": {"destination_id": "GD-A"}},
        )
        self.assertEqual("answered", answered["status"])
        audit = self.request("GET", f"/stores/{store_id}/audit")
        self.assertGreaterEqual(len(audit), 5)
        snapshot = self.request("GET", f"/stores/{store_id}/snapshot")
        self.assertEqual(1, snapshot["evidence_counts"]["system_record"])
        self.assertIn("godown_staff", snapshot["open_tasks_by_role"])
        proofs = self.request("GET", f"/stores/{store_id}/proofs")
        self.assertEqual("awaiting_camera_context", proofs["proofs"][0]["state"])
        self.assertTrue(
            (
                Path(self.temp.name)
                / "store-memory"
                / store_id
                / "Learning"
                / "Operational-Snapshot.md"
            ).exists()
        )


if __name__ == "__main__":
    unittest.main()
