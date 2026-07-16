from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime
from pathlib import Path

from jakasii_ops.connectors import CameraRuntimeInspector


class CameraRuntimeInspectorTests(unittest.TestCase):
    def test_stale_event_store_is_not_reported_as_live_camera(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            database = Path(temp) / "events.sqlite3"
            database.write_bytes(b"not-read-by-health-inspector")
            old = time.time() - 3600
            os.utime(database, (old, old))
            result = CameraRuntimeInspector(temp, stale_seconds=180).inspect()

        self.assertEqual("stale_event_store", result["state"])
        self.assertFalse(result["live_camera_ready"])
        self.assertGreater(result["event_store_age_seconds"], 180)

    def test_fresh_running_heartbeat_is_sanitized(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            data = Path(temp) / "runtime"
            data.mkdir()
            (data / "collector_health.json").write_text(
                json.dumps(
                    {
                        "status": "running",
                        "camera_status": "running",
                        "sql_status": "ok",
                        "updated_at": datetime.now().astimezone().isoformat(),
                        "last_error": "private infrastructure detail",
                        "password": "private secret",
                    }
                ),
                encoding="utf-8",
            )
            result = CameraRuntimeInspector(temp, stale_seconds=180).inspect()

        self.assertEqual("running", result["state"])
        self.assertTrue(result["live_camera_ready"])
        encoded = json.dumps(result)
        self.assertNotIn("private infrastructure", encoded)
        self.assertNotIn("private secret", encoded)
        self.assertFalse(result["raw_error_persisted"])


if __name__ == "__main__":
    unittest.main()
