from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from jakasii_ops.bootstrap import LocalStoreBootstrapper


ROOT = Path(__file__).resolve().parents[1]


class _SchemaConnector:
    def __init__(self, document):
        self.document = document

    def inspect_schema(self):
        return self.document


class LocalStoreBootstrapTests(unittest.TestCase):
    def test_selects_operational_database_and_camera_from_metadata_only(self) -> None:
        modern = json.loads(
            (ROOT / "fixtures/modern_shop/schema.json").read_text(encoding="utf-8")
        )
        weak = {
            "store_id": "bootstrap_shop",
            "name": "Bootstrap Shop",
            "sources": [
                {
                    "name": "archive_source",
                    "kind": "sqlserver",
                    "server": "localhost",
                    "database": "archive",
                    "tables": [
                        {
                            "name": "dbo.logs",
                            "columns": [{"name": "message", "type": "text"}],
                        }
                    ],
                }
            ],
        }
        modern["store_id"] = "bootstrap_shop"
        modern["name"] = "Bootstrap Shop"
        modern["sources"][0].update(
            {
                "kind": "sqlserver",
                "server": "localhost",
                "database": "operations",
            }
        )
        documents = {"archive": weak, "operations": modern}

        with tempfile.TemporaryDirectory() as temp:
            collector = Path(temp) / "unfamiliar_collector"
            collector.mkdir()
            (collector / "device.json").write_text(
                json.dumps(
                    {
                        "password": "must-never-leave-config",
                        "rtsp_url": "rtsp://private-stream",
                        "cameras": [
                            {"channel": 1, "role": "receiving", "enabled": True},
                            {"channel": 2, "role": "godown", "enabled": True},
                        ],
                    }
                ),
                encoding="utf-8",
            )
            (collector / "collector.py").write_text("pass\n", encoding="utf-8")
            (collector / "jakasii_collector.json").write_text(
                json.dumps(
                    {
                        "protocol": "jakasii.camera_collector.v1",
                        "command": ["{python}", "collector.py"],
                        "working_directory": ".",
                        "health_file": "runtime/health.json",
                        "required_environment": ["CAMERA_TEST_SECRET"],
                        "optional_environment": [],
                    }
                ),
                encoding="utf-8",
            )
            bootstrapper = LocalStoreBootstrapper(
                store_id="bootstrap_shop",
                store_name="Bootstrap Shop",
                scan_roots=(temp,),
                server_candidates=("localhost",),
                database_lister=lambda _server: ["archive", "operations"],
                sql_connector_factory=lambda _server, database, _store_id, _name: _SchemaConnector(
                    documents[database]
                ),
            )
            result = bootstrapper.discover()

        self.assertEqual("operations", result["selection"]["database"])
        self.assertEqual(str(collector.resolve()), result["selection"]["camera_root"])
        self.assertIn(
            "product_catalog", result["sql_selection"]["operational_roles"]
        )
        self.assertEqual(2, result["camera_selection"]["camera_channels"])
        self.assertEqual(
            "jakasii.camera_collector.v1",
            result["camera_selection"]["runtime_manifest"]["protocol"],
        )
        self.assertFalse(
            result["camera_selection"]["runtime_manifest"]["contains_secret_values"]
        )
        encoded = json.dumps(result)
        self.assertNotIn("must-never-leave-config", encoded)
        self.assertNotIn("private-stream", encoded)

    def test_database_listing_is_fixed_metadata_query(self) -> None:
        captured: list[str] = []

        class Master:
            def _run_json(self, query):
                captured.append(query)
                return [{"name": "one"}, {"name": "two"}]

        bootstrapper = LocalStoreBootstrapper(
            "shop", "Shop", sql_connector_factory=lambda *_args: Master()
        )
        databases = bootstrapper._databases("localhost")

        self.assertEqual(["one", "two"], databases)
        self.assertEqual(1, len(captured))
        self.assertIn("sys.databases", captured[0])
        self.assertIn("HAS_DBACCESS", captured[0])
        self.assertNotIn("DROP", captured[0].upper())


if __name__ == "__main__":
    unittest.main()
