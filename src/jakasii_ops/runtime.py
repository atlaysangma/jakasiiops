from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ApprovedCameraCollectorLauncher:
    """Launch one manifest-declared collector only after policy approval."""

    root: str | Path
    manifest: dict[str, Any]

    def _command(self) -> tuple[list[str], Path]:
        root = Path(self.root).resolve()
        if self.manifest.get("protocol") != "jakasii.camera_collector.v1":
            raise ValueError("Unsupported camera collector manifest protocol.")
        command = self.manifest.get("command")
        if not isinstance(command, list) or len(command) < 2 or command[0] != "{python}":
            raise ValueError("Camera collector manifest has an unsafe command.")
        script = Path(str(command[1]))
        if script.is_absolute() or ".." in script.parts or script.suffix.lower() != ".py":
            raise ValueError("Camera collector script must be a relative Python file.")
        resolved_script = (root / script).resolve()
        resolved_script.relative_to(root)
        if not resolved_script.is_file():
            raise FileNotFoundError("Camera collector script is unavailable.")
        working = (root / str(self.manifest.get("working_directory", "."))).resolve()
        working.relative_to(root)
        if not working.is_dir():
            raise FileNotFoundError("Camera collector working directory is unavailable.")
        args = [sys.executable, str(resolved_script)] + [str(item) for item in command[2:]]
        return args, working

    def start(self, action: dict[str, Any]) -> dict[str, Any]:
        if (
            action.get("action") != "authorize_start_camera_collector"
            or action.get("target") != "local_camera_collector"
            or action.get("status") != "approved"
        ):
            raise PermissionError("Camera collector launch requires its approved action.")
        required = [str(item) for item in self.manifest.get("required_environment", [])]
        missing = [item for item in required if not os.environ.get(item, "").strip()]
        if missing:
            return {
                "state": "awaiting_required_environment",
                "missing_environment_names": missing,
                "secret_values_persisted": False,
            }
        command, working = self._command()
        creation_flags = subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0
        process = subprocess.Popen(
            command,
            cwd=working,
            env=os.environ.copy(),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creation_flags,
        )
        return {
            "state": "started",
            "process_id": process.pid,
            "secret_values_persisted": False,
        }
