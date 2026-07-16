from __future__ import annotations

import json
import tempfile
import unittest
from unittest.mock import patch

from jakasii_ops.brain import JakasiiOpsBrain
from jakasii_ops.models import SetupQuestion
from jakasii_ops.validation import SqlServerMappingValidator


class SqlServerMappingValidationTests(unittest.TestCase):
    @staticmethod
    def _model():
        source = "sqlserver_localhost_demo"
        tables = [
            {
                "name": "catalog.items",
                "columns": [
                    {"name": "sku_code", "type": "varchar"},
                    {"name": "pack_factor", "type": "decimal"},
                ],
            },
            {
                "name": "inward.lines",
                "columns": [{"name": "received_units", "type": "decimal"}],
            },
            {
                "name": "stock.moves",
                "columns": [{"name": "to_location", "type": "varchar"}],
            },
        ]
        paths = {table["name"]: f"{source}.{table['name']}" for table in tables}
        catalog = {
            "sources": [
                {
                    "name": source,
                    "kind": "sqlserver",
                    "server": "localhost",
                    "database": "demo",
                    "tables": tables,
                }
            ]
        }
        awareness = {
            "role_candidates": {
                "product_catalog": [
                    {"source_path": paths["catalog.items"], "confidence": 0.96}
                ],
                "purchase_line": [
                    {"source_path": paths["inward.lines"], "confidence": 0.96}
                ],
                "stock_movement": [
                    {"source_path": paths["stock.moves"], "confidence": 0.96}
                ],
            }
        }
        profile = {
            "store_id": "shop_1",
            "name": "Shop One",
            "mappings": [
                {
                    "canonical_field": "product.identity",
                    "source_path": f"{paths['catalog.items']}.sku_code",
                    "confidence": 0.98,
                    "verified": False,
                },
                {
                    "canonical_field": "product.pack_size",
                    "source_path": f"{paths['catalog.items']}.pack_factor",
                    "confidence": 0.96,
                    "verified": False,
                },
                {
                    "canonical_field": "purchase.quantity",
                    "source_path": f"{paths['inward.lines']}.received_units",
                    "confidence": 0.98,
                    "verified": False,
                },
                {
                    "canonical_field": "movement.destination",
                    "source_path": f"{paths['stock.moves']}.to_location",
                    "confidence": 0.98,
                    "verified": False,
                },
            ],
        }
        return catalog, awareness, profile

    @patch("jakasii_ops.connectors.SqlServerConnector._run_json")
    def test_only_strong_aggregate_shapes_promote_mappings(self, run_json) -> None:
        catalog, awareness, profile = self._model()
        run_json.side_effect = [
            [{"row_count": 30034, "nonnull_count": 30034, "distinct_count": 30005}],
            [
                {
                    "row_count": 2668,
                    "nonnull_count": 2668,
                    "positive_count": 2668,
                    "negative_count": 0,
                }
            ],
            [
                {
                    "row_count": 30034,
                    "nonnull_count": 8451,
                    "positive_count": 1,
                    "negative_count": 0,
                }
            ],
            [{"row_count": 0, "nonnull_count": 0, "distinct_count": 0}],
        ]
        validator = SqlServerMappingValidator(
            "localhost", "demo", "shop_1", "Shop One", catalog, awareness, profile
        )
        reports = validator.validate()

        passed = {
            item["canonical_field"] for item in reports if item["passed"]
        }
        self.assertEqual({"product.identity", "purchase.quantity"}, passed)
        encoded = json.dumps(reports)
        self.assertNotIn("SKU-", encoded)
        self.assertNotIn("person", encoded.lower())
        self.assertNotIn("SELECT", encoded)

    @patch("jakasii_ops.connectors.SqlServerConnector._run_json")
    def test_brain_resolves_only_questions_proven_by_validator(self, run_json) -> None:
        catalog, awareness, profile = self._model()
        run_json.side_effect = [
            [{"row_count": 100, "nonnull_count": 100, "distinct_count": 100}],
            [{"row_count": 100, "nonnull_count": 100, "positive_count": 100, "negative_count": 0}],
            [{"row_count": 100, "nonnull_count": 1, "positive_count": 1, "negative_count": 0}],
            [{"row_count": 0, "nonnull_count": 0, "distinct_count": 0}],
        ]
        with tempfile.TemporaryDirectory() as temp:
            brain = JakasiiOpsBrain(temp)
            try:
                brain.storage.set_setting("shop_1", "profile", profile)
                brain.storage.set_setting("shop_1", "schema_catalog", catalog)
                brain.storage.set_setting("shop_1", "awareness", awareness)
                for canonical in (
                    "product.identity",
                    "purchase.quantity",
                    "product.pack_size",
                    "movement.destination",
                ):
                    brain.storage.put_record(
                        "setup_question",
                        SetupQuestion(
                            store_id="shop_1",
                            key=f"verify:{canonical}",
                            prompt="Confirm mapping",
                            reason="Test validation",
                        ).to_dict(),
                    )
                result = brain.validate_sql_mappings(
                    SqlServerMappingValidator(
                        "localhost",
                        "demo",
                        "shop_1",
                        "Shop One",
                        catalog,
                        awareness,
                        profile,
                    )
                )
                unresolved = brain.onboarding.questions("shop_1")
            finally:
                brain.close()

        self.assertEqual(
            ["product.identity", "purchase.quantity"], result["promoted"]
        )
        self.assertEqual(
            {"verify:product.pack_size", "verify:movement.destination"},
            {item["key"] for item in unresolved},
        )


if __name__ == "__main__":
    unittest.main()
