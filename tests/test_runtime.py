from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jakasii_ops.runtime import ApprovedCameraCollectorLauncher


class ApprovedCameraCollectorLauncherTests(unittest.TestCase):
    def _fixture(self, root: Path):
        marker = root / "started.marker"
        (root / "collector.py").write_text(
            "from pathlib import Path\nPath('started.marker').write_text('ok')\n",
            encoding="utf-8",
        )
        manifest = {
            "protocol": "jakasii.camera_collector.v1",
            "command": ["{python}", "collector.py"],
            "working_directory": ".",
            "health_file": "health.json",
            "required_environment": ["JAKASII_TEST_CAMERA_SECRET"],
        }
        action = {
            "action": "authorize_start_camera_collector",
            "target": "local_camera_collector",
            "status": "approved",
        }
        return marker, manifest, action

    def test_missing_secret_name_is_reported_without_value(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _marker, manifest, action = self._fixture(root)
            with patch.dict(os.environ, {}, clear=True):
                result = ApprovedCameraCollectorLauncher(root, manifest).start(action)

        self.assertEqual("awaiting_required_environment", result["state"])
        self.assertEqual(
            ["JAKASII_TEST_CAMERA_SECRET"], result["missing_environment_names"]
        )
        self.assertFalse(result["secret_values_persisted"])

    def test_approved_manifest_launches_without_persisting_secret(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _marker, manifest, action = self._fixture(root)
            with patch.dict(
                os.environ, {"JAKASII_TEST_CAMERA_SECRET": "never-persist-this"}
            ), patch("jakasii_ops.runtime.subprocess.Popen") as popen:
                popen.return_value.pid = 4321
                result = ApprovedCameraCollectorLauncher(root, manifest).start(action)

        self.assertEqual("started", result["state"])
        self.assertEqual(4321, result["process_id"])
        popen.assert_called_once()
        self.assertFalse(result["secret_values_persisted"])
        self.assertNotIn("never-persist-this", str(result))

    def test_unapproved_action_cannot_launch(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            _marker, manifest, action = self._fixture(root)
            action["status"] = "pending_approval"
            with self.assertRaises(PermissionError):
                ApprovedCameraCollectorLauncher(root, manifest).start(action)


if __name__ == "__main__":
    unittest.main()
