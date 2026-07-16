from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from threading import Event
from typing import Any, Callable

from .brain import JakasiiOpsBrain
from .connectors import (
    CameraRuntimeInspector,
    CompositeSchemaConnector,
    FirestoreStaffRoleConnector,
    LocalCameraEventConnector,
    LocalCameraSystemConnector,
    LocalVerifiedOperationConnector,
    SqlServerConnector,
    SqlServerOperationalFactConnector,
)
from .validation import SqlServerMappingValidator
from .runtime import ApprovedCameraCollectorLauncher


@dataclass(slots=True)
class StoreAgentConfig:
    store_id: str
    store_name: str
    server: str
    database: str
    camera_root: str | Path
    staff_service_account: str | Path | None = None
    poll_interval_seconds: float = 30.0
    rescan_interval_seconds: float = 3600.0
    sql_limit_per_operation: int = 10
    correlation_window_minutes: int = 15
    backfill_existing: bool = False
    validate_mappings: bool = True
    camera_runtime_manifest: dict[str, Any] | None = None


class StoreAgent:
    """Continuous, headless, failure-isolated store understanding loop."""

    def __init__(
        self,
        brain: JakasiiOpsBrain,
        config: StoreAgentConfig,
        *,
        schema_connector_factory: Callable[[], Any] | None = None,
        camera_connector_factory: Callable[[], Any] | None = None,
        verified_connector_factory: Callable[[], Any] | None = None,
        sql_fact_connector_factory: Callable[[], Any] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.brain = brain
        self.config = config
        self._schema_connector_factory = schema_connector_factory
        self._camera_connector_factory = camera_connector_factory
        self._verified_connector_factory = verified_connector_factory
        self._sql_fact_connector_factory = sql_fact_connector_factory
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._stop = Event()

    def _schema_connector(self) -> Any:
        if self._schema_connector_factory:
            return self._schema_connector_factory()
        connectors: list[Any] = [
            SqlServerConnector(
                self.config.server,
                self.config.database,
                self.config.store_id,
                self.config.store_name,
            ),
            LocalCameraSystemConnector(
                self.config.camera_root,
                self.config.store_id,
                self.config.store_name,
            ),
        ]
        account = self.config.staff_service_account or os.getenv(
            "JAKASII_FIREBASE_SERVICE_ACCOUNT"
        )
        if account:
            connectors.append(
                FirestoreStaffRoleConnector(
                    account,
                    self.config.store_id,
                    self.config.store_name,
                )
            )
        return CompositeSchemaConnector(
            tuple(connectors), self.config.store_id, self.config.store_name
        )

    def _camera_connector(self) -> Any:
        if self._camera_connector_factory:
            return self._camera_connector_factory()
        return LocalCameraEventConnector(self.config.camera_root)

    def _verified_connector(self) -> Any:
        if self._verified_connector_factory:
            return self._verified_connector_factory()
        return LocalVerifiedOperationConnector(self.config.camera_root)

    def _sql_fact_connector(self) -> Any:
        if self._sql_fact_connector_factory:
            return self._sql_fact_connector_factory()
        return SqlServerOperationalFactConnector(
            server=self.config.server,
            database=self.config.database,
            store_id=self.config.store_id,
            store_name=self.config.store_name,
            schema_catalog=self.brain.schema_catalog(self.config.store_id),
            awareness=self.brain.awareness(self.config.store_id),
            profile=self.brain.profile(self.config.store_id),
            limit_per_operation=self.config.sql_limit_per_operation,
        )

    @staticmethod
    def _safe_error(component: str, exc: Exception) -> dict[str, str]:
        return {"component": component, "error": type(exc).__name__}

    def _ensure_camera_runtime_action(
        self, camera_runtime: dict[str, Any]
    ) -> str | None:
        if camera_runtime.get("live_camera_ready"):
            return None
        existing = next(
            (
                item
                for item in self.brain.actions(self.config.store_id)
                if item.get("action") == "authorize_start_camera_collector"
                and item.get("target") == "local_camera_collector"
                and item.get("status") in {"pending_approval", "approved", "allowed"}
            ),
            None,
        )
        if existing:
            return str(existing.get("id"))
        request = self.brain.request_action(
            store_id=self.config.store_id,
            action="authorize_start_camera_collector",
            target="local_camera_collector",
            reason=(
                "The camera configuration is connected but its collector heartbeat/events "
                "are not live. An owner must authorize the collector runtime and provide "
                "its secrets outside JAKASII memory."
            ),
            authority="system_change",
            payload={
                "runtime_state": camera_runtime.get("state"),
                "secret_values_requested_in_payload": False,
            },
            reversible=True,
            data_leaving_device=False,
        )
        return str(request["id"])

    def _execute_camera_runtime_action(
        self, action_id: str | None, camera_runtime: dict[str, Any]
    ) -> dict[str, Any]:
        if camera_runtime.get("live_camera_ready"):
            return {"state": "already_running"}
        if not action_id:
            return {"state": "no_action"}
        action = self.brain.storage.get_record(action_id)
        if not action:
            return {"state": "action_missing"}
        if action.get("status") == "pending_approval":
            return {"state": "awaiting_approval"}
        if action.get("status") == "executed":
            return {"state": "launch_recorded"}
        if action.get("status") != "approved":
            return {"state": "not_executable"}
        if not self.config.camera_runtime_manifest:
            return {"state": "runtime_manifest_unavailable"}
        try:
            result = ApprovedCameraCollectorLauncher(
                self.config.camera_root, self.config.camera_runtime_manifest
            ).start(action)
        except Exception as exc:
            return {"state": "launch_failed", "error": type(exc).__name__}
        if result.get("state") == "started":
            self.brain.mark_action_executed(self.config.store_id, action_id, result)
        return result

    def _rescan_due(self, now: datetime, force: bool) -> bool:
        if force or not self.brain.profile(self.config.store_id):
            return True
        last = self.brain.storage.get_setting(
            self.config.store_id, "agent:last_rescan_at"
        )
        if not last:
            return True
        try:
            previous = datetime.fromisoformat(str(last).replace("Z", "+00:00"))
        except ValueError:
            return True
        return (now - previous).total_seconds() >= max(
            1.0, self.config.rescan_interval_seconds
        )

    def run_cycle(self, *, force_rescan: bool = False) -> dict[str, Any]:
        started = self._now()
        errors: list[dict[str, str]] = []
        rescan: dict[str, Any] = {"attempted": False, "completed": False}
        imports = {"camera": 0, "verified": 0, "sql": 0}
        primed = {"camera": 0, "verified": 0, "sql": 0}
        events_created = 0
        first_cycle = not bool(self.brain.agent_status(self.config.store_id))

        if self._rescan_due(started, force_rescan):
            rescan["attempted"] = True
            try:
                onboarding = self.brain.onboard_connector(self._schema_connector())
                rescan.update(
                    {
                        "completed": True,
                        "tables": onboarding["profile"].get("discovered_tables", 0),
                        "columns": onboarding["profile"].get("discovered_columns", 0),
                        "questions": len(onboarding.get("questions", [])),
                        "ready": bool(onboarding["readiness"].get("ready")),
                    }
                )
                self.brain.storage.set_setting(
                    self.config.store_id,
                    "agent:last_rescan_at",
                    started.isoformat(),
                )
            except Exception as exc:
                errors.append(self._safe_error("schema_rescan", exc))

            if rescan["completed"] and self.config.validate_mappings:
                try:
                    validation = self.brain.validate_sql_mappings(
                        SqlServerMappingValidator(
                            server=self.config.server,
                            database=self.config.database,
                            store_id=self.config.store_id,
                            store_name=self.config.store_name,
                            schema_catalog=self.brain.schema_catalog(
                                self.config.store_id
                            ),
                            awareness=self.brain.awareness(self.config.store_id),
                            profile=self.brain.profile(self.config.store_id),
                        )
                    )
                    rescan["validated_mappings"] = validation["promoted"]
                    rescan["questions"] = validation["readiness"][
                        "unresolved_questions"
                    ]
                    rescan["ready"] = bool(validation["readiness"]["ready"])
                except Exception as exc:
                    errors.append(self._safe_error("mapping_validation", exc))

        for component, connector_factory in (
            ("camera", self._camera_connector),
            ("verified", self._verified_connector),
        ):
            try:
                connector = connector_factory()
                if first_cycle and not self.config.backfill_existing:
                    baseline = self.brain.prime_evidence_connector(
                        self.config.store_id, connector
                    )
                    primed[component] = int(baseline.get("primed", 0))
                else:
                    ingestion = self.brain.ingest_evidence_connector(
                        self.config.store_id, connector
                    )
                    imports[component] = int(ingestion.get("imported", 0))
            except Exception as exc:
                errors.append(self._safe_error(component, exc))

        if self.brain.schema_catalog(self.config.store_id):
            try:
                connector = self._sql_fact_connector()
                if first_cycle and not self.config.backfill_existing:
                    baseline = self.brain.prime_evidence_connector(
                        self.config.store_id, connector
                    )
                    primed["sql"] = int(baseline.get("primed", 0))
                    errors.extend(
                        {"component": "sql", "error": "ConnectorDiagnostic"}
                        for _item in getattr(connector, "errors", [])
                    )
                else:
                    cycle = self.brain.run_operational_cycle(
                        self.config.store_id, connector
                    )
                    imports["sql"] = int(cycle.get("imported", 0))
                    events_created = int(cycle.get("events_created", 0))
                    errors.extend(
                        {"component": "sql", "error": "ConnectorDiagnostic"}
                        for _item in cycle.get("connector_errors", [])
                    )
            except Exception as exc:
                errors.append(self._safe_error("sql", exc))

        try:
            camera_runtime = CameraRuntimeInspector(
                self.config.camera_root,
                stale_seconds=max(180, int(self.config.poll_interval_seconds * 3)),
            ).inspect()
            self.brain.storage.set_setting(
                self.config.store_id, "camera:runtime", camera_runtime
            )
        except Exception as exc:
            errors.append(self._safe_error("camera_runtime", exc))
            camera_runtime = {
                "state": "unavailable",
                "live_camera_ready": False,
                "raw_error_persisted": False,
            }
        camera_runtime_action_id = self._ensure_camera_runtime_action(camera_runtime)
        camera_runtime_launch = self._execute_camera_runtime_action(
            camera_runtime_action_id, camera_runtime
        )

        try:
            snapshot = self.brain.operational_snapshot(
                self.config.store_id, self.config.correlation_window_minutes
            )
        except Exception as exc:
            errors.append(self._safe_error("snapshot", exc))
            snapshot = {"state": "unavailable", "attention": []}

        try:
            proofs = self.brain.operation_proofs(
                self.config.store_id, self.config.correlation_window_minutes
            )
        except Exception as exc:
            errors.append(self._safe_error("operation_proofs", exc))
            proofs = {"complete_count": 0, "state_counts": {}}

        completed = self._now()
        status = {
            "store_id": self.config.store_id,
            "mode": "headless_store_agent",
            "cycle_started_at": started.isoformat(),
            "cycle_completed_at": completed.isoformat(),
            "healthy": not errors,
            "rescan": rescan,
            "imports": imports,
            "primed": primed,
            "events_created": events_created,
            "snapshot_state": snapshot.get("state"),
            "operation_proofs": {
                "complete": int(proofs.get("complete_count", 0)),
                "states": proofs.get("state_counts", {}),
            },
            "camera_runtime": camera_runtime,
            "camera_runtime_action_id": camera_runtime_action_id,
            "camera_runtime_launch": camera_runtime_launch,
            "attention": snapshot.get("attention", [])
            + (
                [
                    "Live camera collector is not ready; fresh physical context cannot be proven."
                ]
                if not camera_runtime.get("live_camera_ready")
                else []
            ),
            "errors": errors,
            "connection_scopes": {
                "sqlserver": True,
                "camera_collector": True,
                "staff_roles": bool(
                    self.config.staff_service_account
                    or os.getenv("JAKASII_FIREBASE_SERVICE_ACCOUNT")
                ),
            },
        }
        self.brain.storage.set_setting(
            self.config.store_id, "agent:status", status
        )
        self.brain.storage.add_audit(
            self.config.store_id,
            "agent_cycle_completed",
            "jakasii",
            "store_agent",
            {
                "healthy": status["healthy"],
                "imports": imports,
                "primed": primed,
                "events_created": events_created,
                "error_components": [item["component"] for item in errors],
            },
        )
        return status

    def run(
        self,
        max_cycles: int | None = None,
        on_cycle: Callable[[dict[str, Any]], None] | None = None,
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        cycles = 0
        while not self._stop.is_set() and (max_cycles is None or cycles < max_cycles):
            result = self.run_cycle(force_rescan=cycles == 0)
            if max_cycles is not None:
                results.append(result)
            else:
                results[:] = [result]
            if on_cycle:
                on_cycle(result)
            cycles += 1
            if max_cycles is not None and cycles >= max_cycles:
                break
            self._stop.wait(max(0.1, self.config.poll_interval_seconds))
        return results

    def stop(self) -> None:
        self._stop.set()
