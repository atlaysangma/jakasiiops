from __future__ import annotations

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WINDOWS = ROOT / "deployment" / "windows"


class MainServerDeploymentAssetsTests(unittest.TestCase):
    def test_runtime_scripts_are_present(self) -> None:
        expected = {
            "Install-JakasiiOps.ps1",
            "Run-JakasiiOps.ps1",
            "Start-JakasiiOps.ps1",
            "Stop-JakasiiOps.ps1",
            "Get-JakasiiOpsStatus.ps1",
            "Uninstall-JakasiiOps.ps1",
        }
        present = {path.name for path in (WINDOWS / "runtime").glob("*.ps1")}
        self.assertEqual(expected, present)

    def test_install_registers_disabled_user_scoped_task(self) -> None:
        script = (WINDOWS / "runtime" / "Install-JakasiiOps.ps1").read_text(encoding="utf-8")
        self.assertIn("-LogonType Interactive", script)
        self.assertIn("-RunLevel Limited", script)
        self.assertIn("Disable-ScheduledTask", script)
        self.assertNotIn("-RunLevel Highest", script)

    def test_package_and_config_declare_no_secrets_or_production_data(self) -> None:
        build = (WINDOWS / "Build-MainServerPackage.ps1").read_text(encoding="utf-8")
        install = (WINDOWS / "runtime" / "Install-JakasiiOps.ps1").read_text(encoding="utf-8")
        self.assertIn('contains_secrets = $false', build)
        self.assertIn('contains_production_data = $false', build)
        self.assertIn('contains_secrets = $false', install)
        forbidden = re.compile(r"(?im)^\s*(password|api[_-]?key|token|connection[_-]?string)\s*=")
        self.assertIsNone(forbidden.search(build + "\n" + install))


if __name__ == "__main__":
    unittest.main()
