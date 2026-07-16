from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jakasii_ops.brain import JakasiiOpsBrain
from jakasii_ops.connectors import SqlServerConnector


ROOT = Path(__file__).resolve().parents[1]


class SqlServerConnectorTests(unittest.TestCase):
    @patch("jakasii_ops.connectors.shutil.which", return_value=r"C:\tools\sqlcmd.exe")
    @patch("jakasii_ops.connectors.subprocess.run")
    def test_discovers_schema_without_domain_table_hints(self, run_mock, _which_mock) -> None:
        rows = [
            {
                "schema_name": "dbo",
                "table_name": "OddHeader",
                "column_name": "RecordKey",
                "data_type": "int",
                "max_length": 4,
                "precision": 10,
                "scale": 0,
                "is_nullable": False,
                "is_primary_key": True,
            },
            {
                "schema_name": "dbo",
                "table_name": "OddHeader",
                "column_name": "UnknownValue",
                "data_type": "decimal",
                "max_length": 9,
                "precision": 18,
                "scale": 2,
                "is_nullable": True,
                "is_primary_key": False,
            },
        ]
        payloads = (
            rows,
            [{"schema_name": "dbo", "table_name": "OddHeader", "row_count": 7}],
            [
                {
                    "from_schema": "dbo",
                    "from_table": "OddHeader",
                    "from_column": "RecordKey",
                    "to_schema": "dbo",
                    "to_table": "OtherMaster",
                    "to_column": "RecordKey",
                    "constraint_name": "FK_Odd_Other",
                }
            ],
        )
        completed = []
        for index, payload in enumerate(payloads):
            encoded = json.dumps(payload)
            if index == 0:
                encoded = encoded[:37] + "\n" + encoded[37:]
            completed.append(
                subprocess.CompletedProcess(
                    args=[],
                    returncode=0,
                    stdout="JSON_F52E2B61-18A1-11d1-B105-00805F49916B\n" + encoded,
                    stderr="",
                )
            )
        run_mock.side_effect = completed
        connector = SqlServerConnector("localhost", "UnknownDb", "shop_1", "Unknown Shop")

        document = connector.inspect_schema()

        source = document["sources"][0]
        self.assertEqual("read_only_discovery", source["access"])
        self.assertEqual("dbo.OddHeader", source["tables"][0]["name"])
        self.assertEqual(7, source["tables"][0]["row_count"])
        self.assertTrue(source["tables"][0]["columns"][0]["primary_key"])
        self.assertEqual("declared_foreign_key", source["relationships"][0]["kind"])
        for call in run_mock.call_args_list:
            query = call.args[0][-1].upper()
            self.assertNotIn("INSERT ", query)
            self.assertNotIn("UPDATE ", query)
            self.assertNotIn("DELETE ", query)

    @patch("jakasii_ops.connectors.shutil.which", return_value=r"C:\tools\sqlcmd.exe")
    @patch("jakasii_ops.connectors.subprocess.run")
    def test_rejects_unsafe_sample_table_before_sqlcmd(self, run_mock, _which_mock) -> None:
        connector = SqlServerConnector("localhost", "UnknownDb", "shop_1", "Unknown Shop")
        with self.assertRaises(ValueError):
            connector.sample_records("dbo.Products; DROP TABLE Products", 2)
        run_mock.assert_not_called()

    def test_live_connector_document_uses_normal_onboarding_boundary(self) -> None:
        fixture = json.loads((ROOT / "fixtures/modern_shop/schema.json").read_text(encoding="utf-8"))
        fixture.pop("schema_file", None)
        fixture["schema_source"] = {
            "connector": "sqlserver",
            "server": "localhost",
            "database": "synthetic",
            "authentication": "windows",
        }

        class FakeConnector:
            name = "fake_sqlserver"

            def inspect_schema(self):
                return fixture

            def sample_records(self, table: str, limit: int = 5):
                return []

        with tempfile.TemporaryDirectory() as temp:
            brain = JakasiiOpsBrain(temp)
            try:
                result = brain.onboard_connector(FakeConnector())
                self.assertTrue(result["readiness"]["ready"])
                self.assertGreater(result["profile"]["discovered_tables"], 0)
                self.assertGreater(result["profile"]["discovered_columns"], 0)
                self.assertEqual("sqlserver", result["profile"]["schema_source"]["connector"])
                catalog = brain.schema_catalog(result["profile"]["store_id"])
                catalog_columns = [
                    column
                    for source in catalog["sources"]
                    for table in source["tables"]
                    for column in table["columns"]
                ]
                self.assertTrue(catalog_columns)
                self.assertTrue(all("samples" not in column for column in catalog_columns))
                self.assertTrue(
                    (
                        Path(temp)
                        / "store-memory"
                        / result["profile"]["store_id"]
                        / "Learning"
                        / "Schema-Catalog.json"
                    ).exists()
                )
            finally:
                brain.close()


if __name__ == "__main__":
    unittest.main()
