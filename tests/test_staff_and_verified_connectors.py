from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from jakasii_ops.brain import JakasiiOpsBrain
from jakasii_ops.connectors import (
    FirestoreStaffRoleConnector,
    LocalVerifiedOperationConnector,
    SqlServerOperationalFactConnector,
)


class _Document:
    def __init__(self, role: str, private_name: str) -> None:
        self.role = role
        self.private_name = private_name

    def to_dict(self):
        return {"role": self.role, "name": self.private_name, "email": "private@example.test"}


class _Query:
    def __init__(self, documents):
        self.documents = documents

    def select(self, fields):
        if fields != ["role"]:
            raise AssertionError("connector requested private staff fields")
        return self

    def stream(self):
        return iter(self.documents)


class _Client:
    def collection(self, name):
        if name != "userstaff":
            raise AssertionError("unexpected collection")
        return _Query(
            [
                _Document("Data Entry Operator", "Private One"),
                _Document("deo", "Private Two"),
                _Document("godown", "Private Three"),
            ]
        )


class StaffAndVerifiedConnectorTests(unittest.TestCase):
    @staticmethod
    def _operational_model():
        source_name = "sqlserver_localhost_demo"
        def column(name, primary=False):
            return {"name": name, "type": "text", "primary_key": primary}
        tables = [
            {"name": "ops.receipts", "row_count": 3, "columns": [column("ReceiptId", True), column("CreatedAt")]},
            {"name": "ops.receipt_lines", "row_count": 8, "columns": [column("LineId", True), column("ReceiptId"), column("ProductId"), column("Quantity"), column("LocationId")]},
            {"name": "ops.products", "row_count": 20, "columns": [column("ProductId", True), column("SKU"), column("UnitsPerCase")]},
        ]
        paths = {table["name"]: f"{source_name}.{table['name']}" for table in tables}
        catalog = {"sources": [{"name": source_name, "kind": "sqlserver", "server": "localhost", "database": "demo", "tables": tables}]}
        awareness = {
            "role_candidates": {
                "purchase_header": [{"source_path": paths["ops.receipts"], "confidence": 0.9, "row_count": 3}],
                "purchase_line": [{"source_path": paths["ops.receipt_lines"], "confidence": 0.94, "row_count": 8}],
                "product_catalog": [{"source_path": paths["ops.products"], "confidence": 0.95, "row_count": 20}],
            },
            "inferred_relationships": [
                {"from_table": paths["ops.receipts"], "from_column": "ReceiptId", "to_table": paths["ops.receipt_lines"], "to_column": "ReceiptId", "confidence": 0.9},
                {"from_table": paths["ops.receipt_lines"], "from_column": "ProductId", "to_table": paths["ops.products"], "to_column": "ProductId", "confidence": 0.9},
            ],
        }
        profile = {
            "mappings": [
                {"canonical_field": "product.identity", "source_path": f"{paths['ops.products']}.SKU", "confidence": 0.97, "verified": False},
                {"canonical_field": "product.pack_size", "source_path": f"{paths['ops.products']}.UnitsPerCase", "confidence": 0.96, "verified": False},
                {"canonical_field": "purchase.quantity", "source_path": f"{paths['ops.receipt_lines']}.Quantity", "confidence": 0.98, "verified": False},
            ]
        }
        return catalog, awareness, profile

    def test_staff_discovery_exposes_only_aggregate_roles(self) -> None:
        connector = FirestoreStaffRoleConnector(
            "never-opened.json",
            "shop_1",
            "Shop One",
            client_factory=lambda: _Client(),
        )
        document = connector.inspect_schema()
        encoded = json.dumps(document)

        roles = document["sources"][0]["entities"]["staff_roles"]
        self.assertEqual(
            [{"role": "deo", "count": 2}, {"role": "godown_incharge", "count": 1}],
            roles,
        )
        self.assertNotIn("Private", encoded)
        self.assertNotIn("example.test", encoded)
        self.assertNotIn("never-opened", encoded)
        self.assertNotIn("uid", encoded.lower())
        self.assertEqual(
            [
                {
                    "canonical_field": "staff.role",
                    "table": "staff_directory",
                    "column": "role",
                    "authority": "authorized_connector_contract",
                }
            ],
            document["sources"][0]["semantic_contracts"],
        )

    def test_verified_operations_preserve_evidence_kind_and_remove_private_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            collector = root / "collector"
            collector.mkdir()
            database = collector / "events.sqlite3"
            connection = sqlite3.connect(database)
            connection.execute(
                "CREATE TABLE verified_labels (event_id TEXT PRIMARY KEY, action TEXT NOT NULL, "
                "staff_uid TEXT, staff_name TEXT, product_sku TEXT, product_name TEXT, quantity REAL, "
                "source_zone TEXT, destination_shelf TEXT, notes TEXT, verified_by TEXT NOT NULL, "
                "verified_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO verified_labels VALUES "
                "('cam-1','moved','private-uid','Private Staff','SKU-1','Private Product',3," 
                "'godown','shelf-a','private note','Private Manager','2026-01-01T10:00:00Z')"
            )
            connection.execute(
                "CREATE TABLE sql_facts (fact_key TEXT PRIMARY KEY, fact_type TEXT NOT NULL, "
                "occurred_at TEXT NOT NULL, document_id TEXT NOT NULL, line_id TEXT NOT NULL, "
                "product_sku TEXT NOT NULL, product_name TEXT, quantity REAL NOT NULL, amount REAL, "
                "imported_at TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT INTO sql_facts VALUES "
                "('fact-1','purchase','2026-01-01T10:01:00Z','private-doc','private-line'," 
                "'SKU-1','Private Product',3,999,'2026-01-01T10:02:00Z')"
            )
            connection.commit()
            connection.close()

            brain = JakasiiOpsBrain(root / "brain")
            try:
                connector = LocalVerifiedOperationConnector(collector)
                first = brain.ingest_evidence_connector("shop_1", connector)
                second = brain.ingest_evidence_connector("shop_1", connector)
            finally:
                brain.close()

            self.assertEqual(2, first["imported"])
            self.assertEqual(0, second["imported"])
            self.assertEqual(
                {"human_confirmation", "system_record"},
                {item["kind"] for item in first["evidence"]},
            )
            encoded = json.dumps(first)
            for private in (
                "private-uid",
                "Private Staff",
                "Private Manager",
                "private note",
                "Private Product",
                "private-doc",
                "private-line",
                "999",
            ):
                self.assertNotIn(private, encoded)
            system = next(item for item in first["evidence"] if item["kind"] == "system_record")
            self.assertEqual(16, len(system["payload"]["source_record_hash"]))

    @patch("jakasii_ops.connectors.SqlServerConnector._run_json")
    def test_sql_operational_cycle_uses_learned_model_and_routes_real_candidate(self, run_json) -> None:
        catalog, awareness, profile = self._operational_model()
        run_json.return_value = [
            {
                "header_record_id": "private-header-id",
                "line_record_id": "private-line-id",
                "event_date": "2026-07-16T00:00:00",
                "product_id": "SKU-REAL-1",
                "quantity": 24,
                "pack_size": 12,
                "destination_id": "G1",
            }
        ]
        connector = SqlServerOperationalFactConnector(
            "localhost", "demo", "shop_1", "Shop One", catalog, awareness, profile,
            limit_per_operation=1, operation_types=("purchase",),
        )
        with tempfile.TemporaryDirectory() as temp:
            brain = JakasiiOpsBrain(temp)
            try:
                first = brain.run_operational_cycle("shop_1", connector)
                second = brain.run_operational_cycle("shop_1", connector)
            finally:
                brain.close()

        self.assertEqual(1, first["imported"])
        self.assertEqual(1, first["events_created"])
        self.assertEqual("2026-07-16T00:00:00", first["outcomes"][0]["event"]["occurred_at"])
        self.assertEqual(0, second["imported"])
        self.assertEqual(0, second["events_created"])
        evidence_id = first["outcomes"][0]["event"]["evidence_ids"][0]
        self.assertTrue(evidence_id.startswith("evd_"))
        tasks = first["outcomes"][0]["tasks"]
        self.assertEqual({"manager", "godown_staff"}, {item["role"] for item in tasks})
        encoded = json.dumps(first)
        self.assertNotIn("private-header-id", encoded)
        self.assertNotIn("private-line-id", encoded)
        query = run_json.call_args.args[0]
        self.assertIn("[ops].[receipts]", query)
        self.assertIn("[ops].[receipt_lines]", query)
        self.assertNotIn("Customer", query)
        self.assertNotIn("Supplier", query)
        self.assertNotIn("Amount", query)


if __name__ == "__main__":
    unittest.main()
