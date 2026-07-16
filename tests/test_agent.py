from __future__ import annotations

import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

from jakasii_ops.agent import StoreAgent, StoreAgentConfig
from jakasii_ops.brain import JakasiiOpsBrain


ROOT = Path(__file__).resolve().parents[1]


class _SchemaConnector:
    name = "learned_test_store"

    def __init__(self) -> None:
        self.calls = 0

    def inspect_schema(self):
        self.calls += 1
        document = json.loads(
            (ROOT / "fixtures/modern_shop/schema.json").read_text(encoding="utf-8")
        )
        document["store_id"] = "agent_shop"
        document["name"] = "Agent Shop"
        return document

    def sample_records(self, table: str, limit: int = 5):
        return []


class _CameraConnector:
    name = "test_camera"

    def poll(self):
        return [
            {
                "external_id": "camera-1",
                "occurred_at": "2026-07-16T10:00:00+00:00",
                "kind": "observation",
                "confidence": 0.9,
                "payload": {"camera_channel": 1, "camera_claim": "activity_observation_only"},
            }
        ]


class _EmptyConnector:
    name = "empty_verified"

    def poll(self):
        return []


class _FailingConnector:
    name = "failing_verified"

    def poll(self):
        raise RuntimeError("private failure detail must not be persisted")


class _SqlFactConnector:
    name = "test_sql_facts"
    errors = []

    def poll(self):
        return [
            {
                "external_id": "purchase-line-1",
                "occurred_at": "2026-07-16T10:02:00+00:00",
                "kind": "system_record",
                "confidence": 0.95,
                "payload": {
                    "operation_type": "purchase_line",
                    "product_id": "SKU-1",
                    "quantity": 12,
                    "pack_size": 12,
                    "destination_id": "G1",
                    "source_record_hash": "safe-hash",
                    "mapping_verified": True,
                },
            }
        ]


class StoreAgentTests(unittest.TestCase):
    def _config(self) -> StoreAgentConfig:
        return StoreAgentConfig(
            store_id="agent_shop",
            store_name="Agent Shop",
            server="localhost",
            database="ignored_by_fake",
            camera_root="ignored-by-fake",
            poll_interval_seconds=0.1,
            rescan_interval_seconds=3600,
            sql_limit_per_operation=1,
            backfill_existing=True,
            validate_mappings=False,
        )

    def test_continuous_agent_rescans_once_and_deduplicates_future_cycles(self) -> None:
        schema = _SchemaConnector()
        fixed_now = lambda: datetime(2026, 7, 16, 10, 5, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as temp:
            brain = JakasiiOpsBrain(temp)
            try:
                agent = StoreAgent(
                    brain,
                    self._config(),
                    schema_connector_factory=lambda: schema,
                    camera_connector_factory=_CameraConnector,
                    verified_connector_factory=_EmptyConnector,
                    sql_fact_connector_factory=_SqlFactConnector,
                    now=fixed_now,
                )
                first, second = agent.run(max_cycles=2)
                persisted = brain.agent_status("agent_shop")
                audit = brain.audit("agent_shop")
            finally:
                brain.close()

        self.assertTrue(first["rescan"]["completed"])
        self.assertFalse(second["rescan"]["attempted"])
        self.assertEqual(1, schema.calls)
        self.assertEqual({"camera": 1, "verified": 0, "sql": 1}, first["imports"])
        self.assertEqual({"camera": 0, "verified": 0, "sql": 0}, second["imports"])
        self.assertEqual(1, first["events_created"])
        self.assertEqual(0, second["events_created"])
        self.assertEqual(second, persisted)
        self.assertEqual("needs_attention", persisted["snapshot_state"])
        self.assertEqual(2, sum(1 for item in audit if item["action"] == "agent_cycle_completed"))

    def test_connector_failure_is_isolated_and_private_error_text_is_not_saved(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            brain = JakasiiOpsBrain(temp)
            try:
                agent = StoreAgent(
                    brain,
                    self._config(),
                    schema_connector_factory=_SchemaConnector,
                    camera_connector_factory=_CameraConnector,
                    verified_connector_factory=_FailingConnector,
                    sql_fact_connector_factory=_SqlFactConnector,
                    now=lambda: datetime(2026, 7, 16, 10, 5, tzinfo=timezone.utc),
                )
                status = agent.run_cycle(force_rescan=True)
                encoded = json.dumps(status)
            finally:
                brain.close()

        self.assertFalse(status["healthy"])
        self.assertIn({"component": "verified", "error": "RuntimeError"}, status["errors"])
        self.assertEqual(1, status["events_created"])
        self.assertNotIn("private failure detail", encoded)

    def test_default_watch_mode_primes_existing_records_without_old_tasks(self) -> None:
        config = self._config()
        config.backfill_existing = False
        with tempfile.TemporaryDirectory() as temp:
            brain = JakasiiOpsBrain(temp)
            try:
                agent = StoreAgent(
                    brain,
                    config,
                    schema_connector_factory=_SchemaConnector,
                    camera_connector_factory=_CameraConnector,
                    verified_connector_factory=_EmptyConnector,
                    sql_fact_connector_factory=_SqlFactConnector,
                    now=lambda: datetime(2026, 7, 16, 10, 5, tzinfo=timezone.utc),
                )
                first, second = agent.run(max_cycles=2)
                evidence = brain.storage.list_records("agent_shop", "evidence")
                events = brain.storage.list_records("agent_shop", "event")
                tasks = brain.tasks("agent_shop", open_only=False)
                actions = brain.actions("agent_shop")
            finally:
                brain.close()

        self.assertEqual({"camera": 1, "verified": 0, "sql": 1}, first["primed"])
        self.assertEqual({"camera": 0, "verified": 0, "sql": 0}, first["imports"])
        self.assertEqual(0, first["events_created"])
        self.assertEqual({"camera": 0, "verified": 0, "sql": 0}, second["imports"])
        self.assertEqual([], evidence)
        self.assertEqual([], events)
        self.assertEqual([], tasks)
        self.assertEqual(1, len(actions))
        self.assertEqual("authorize_start_camera_collector", actions[0]["action"])
        self.assertEqual("pending_approval", actions[0]["status"])
        self.assertFalse(actions[0]["payload"]["secret_values_requested_in_payload"])


if __name__ == "__main__":
    unittest.main()
