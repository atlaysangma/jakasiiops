from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from jakasii_ops.brain import JakasiiOpsBrain
from jakasii_ops.connectors import (
    CompositeSchemaConnector,
    LocalCameraEventConnector,
    LocalCameraSystemConnector,
)


ROOT = Path(__file__).resolve().parents[1]


class AwarenessTests(unittest.TestCase):
    def test_composite_discovery_builds_camera_and_store_awareness_without_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            camera_root = Path(temp) / "camera-system"
            camera_root.mkdir()
            (camera_root / "shop-camera.json").write_text(
                json.dumps(
                    {
                        "dvr_user": "must-not-leave-connector",
                        "password": "must-not-leave-connector",
                        "cameras": [
                            {"channel": 1, "name": "Receiving", "role": "receiving", "enabled": True},
                            {"channel": 2, "name": "Godown", "role": "storage", "enabled": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            event_dir = camera_root / "runtime"
            event_dir.mkdir()
            event_db = event_dir / "events.sqlite3"
            connection = sqlite3.connect(event_db)
            connection.execute(
                "CREATE TABLE observations (event_id TEXT PRIMARY KEY, camera_channel INTEGER, "
                "started_at TEXT, snapshot_path TEXT, detector TEXT)"
            )
            connection.execute(
                "INSERT INTO observations VALUES ('secret-event-row', 1, '2026-01-01', "
                "'private/frame.jpg', 'person-v1')"
            )
            connection.commit()
            connection.close()

            fixture = json.loads(
                (ROOT / "fixtures/modern_shop/schema.json").read_text(encoding="utf-8")
            )
            fixture["store_id"] = "composite_shop"
            fixture["name"] = "Composite Shop"

            class FixtureConnector:
                name = "fixture_sql"

                def inspect_schema(self):
                    return fixture

                def sample_records(self, table: str, limit: int = 5):
                    return []

            camera = LocalCameraSystemConnector(camera_root, "composite_shop", "Composite Shop")
            composite = CompositeSchemaConnector(
                connectors=(FixtureConnector(), camera),
                store_id="composite_shop",
                store_name="Composite Shop",
            )
            brain_root = Path(temp) / "brain"
            brain = JakasiiOpsBrain(brain_root)
            try:
                result = brain.onboard_connector(composite)
                awareness = brain.awareness("composite_shop")
                catalog_text = json.dumps(brain.schema_catalog("composite_shop"))
                self.assertEqual(2, result["profile"]["discovered_camera_channels"])
                self.assertEqual(2, awareness["camera_channel_count"])
                self.assertIn("camera_registry", awareness["capabilities_observed"])
                self.assertIn("camera_events", awareness["capabilities_observed"])
                self.assertNotIn("must-not-leave-connector", catalog_text)
                self.assertNotIn("secret-event-row", catalog_text)
                self.assertNotIn("private/frame.jpg", catalog_text)
                camera_events = LocalCameraEventConnector(camera_root)
                first_import = brain.ingest_evidence_connector("composite_shop", camera_events)
                second_import = brain.ingest_evidence_connector("composite_shop", camera_events)
                self.assertEqual(1, first_import["imported"])
                self.assertEqual(0, second_import["imported"])
                imported_payload = first_import["evidence"][0]["payload"]
                self.assertEqual("activity_observation_only", imported_payload["camera_claim"])
                self.assertNotIn("snapshot_path", imported_payload)
                self.assertNotIn("private/frame.jpg", json.dumps(imported_payload))
                self.assertTrue(
                    (
                        brain_root
                        / "store-memory"
                        / "composite_shop"
                        / "Learning"
                        / "Store-Awareness.md"
                    ).exists()
                )
            finally:
                brain.close()


if __name__ == "__main__":
    unittest.main()
