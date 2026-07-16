from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionRequest, PolicyGate
from .connectors import EvidenceConnector, SchemaConnector
from .memory import StoreMemory
from .models import (
    Evidence,
    EvidenceKind,
    EventType,
    OperationalEvent,
    TaskStatus,
    utc_now,
)
from .onboarding import OnboardingEngine
from .proof import OperationProofEngine
from .reasoning import DeterministicReasoner, ReasoningProvider
from .storage import OpsStore
from .situational import OperationalSnapshotEngine
from .validation import SqlServerMappingValidator
from .workflows import WorkflowEngine


class JakasiiOpsBrain:
    """Headless coordinator: onboarding, evidence, memory, workflows and audit."""

    def __init__(
        self,
        data_root: str | Path = "data",
        reasoner: ReasoningProvider | None = None,
    ) -> None:
        self.data_root = Path(data_root)
        self.data_root.mkdir(parents=True, exist_ok=True)
        self.reasoner = reasoner or DeterministicReasoner()
        self.storage = OpsStore(self.data_root / "jakasii_ops.db")
        self.onboarding = OnboardingEngine(
            self.storage, self.data_root / "store-memory", self.reasoner
        )
        self.workflows = WorkflowEngine()
        self.policy = PolicyGate()

    def onboard(self, schema_path: str | Path) -> dict[str, Any]:
        return self.onboarding.start(schema_path)

    def onboard_connector(self, connector: SchemaConnector) -> dict[str, Any]:
        return self.onboarding.start_connector(connector)

    def record_bootstrap(self, store_id: str, discovery: dict[str, Any]) -> None:
        """Persist a sanitized autonomous-connection decision for audit."""

        self.storage.set_setting(store_id, "bootstrap:selection", discovery)
        self.storage.add_audit(
            store_id,
            "local_connections_discovered",
            "jakasii",
            "bootstrap_selection",
            {
                "basis": discovery.get("basis"),
                "candidate_counts": discovery.get("candidate_counts", {}),
                "failures": discovery.get("failures", {}),
            },
        )
        StoreMemory(self.data_root / "store-memory", store_id).write_json_artifact(
            "Connection-Bootstrap", discovery
        )

    def validate_sql_mappings(
        self, validator: SqlServerMappingValidator
    ) -> dict[str, Any]:
        return self.onboarding.apply_validations(
            validator.store_id, validator.validate()
        )

    def answer_setup(
        self, store_id: str, question_id: str, answer: Any, actor: str
    ) -> dict[str, Any]:
        return self.onboarding.answer(store_id, question_id, answer, actor)

    def record_evidence(
        self,
        store_id: str,
        kind: str,
        source: str,
        payload: dict[str, Any],
        confidence: float = 1.0,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        evidence = Evidence(
            kind=EvidenceKind(kind),
            source=source,
            payload=payload,
            store_id=store_id,
            confidence=max(0.0, min(float(confidence), 1.0)),
            **({"occurred_at": occurred_at} if occurred_at else {}),
        )
        self.storage.put_record("evidence", evidence.to_dict())
        self.storage.add_audit(
            store_id,
            "evidence_recorded",
            source,
            evidence.id,
            {"kind": kind, "confidence": evidence.confidence},
        )
        return evidence.to_dict()

    def ingest_evidence_connector(
        self, store_id: str, connector: EvidenceConnector
    ) -> dict[str, Any]:
        setting_key = f"connector_seen:{connector.name}"
        seen = set(self.storage.get_setting(store_id, setting_key, []))
        imported: list[dict[str, Any]] = []
        for item in connector.poll():
            external_id = str(item.get("external_id", "")).strip()
            if not external_id or external_id in seen:
                continue
            evidence = self.record_evidence(
                store_id=store_id,
                kind=item.get("kind", EvidenceKind.OBSERVATION),
                source=connector.name,
                payload=item.get("payload", {}),
                confidence=item.get("confidence", 0.5),
                occurred_at=item.get("occurred_at"),
            )
            imported.append(evidence)
            seen.add(external_id)
        self.storage.set_setting(store_id, setting_key, sorted(seen)[-10_000:])
        self.storage.add_audit(
            store_id,
            "connector_polled",
            connector.name,
            connector.name,
            {"imported": len(imported), "seen": len(seen)},
        )
        return {"connector": connector.name, "imported": len(imported), "evidence": imported}

    def prime_evidence_connector(
        self, store_id: str, connector: EvidenceConnector
    ) -> dict[str, Any]:
        """Remember the connector's existing cursor without creating evidence/events."""

        setting_key = f"connector_seen:{connector.name}"
        existing = set(self.storage.get_setting(store_id, setting_key, []))
        discovered = {
            str(item.get("external_id", "")).strip()
            for item in connector.poll()
            if str(item.get("external_id", "")).strip()
        }
        new_ids = discovered - existing
        seen = existing | discovered
        self.storage.set_setting(store_id, setting_key, sorted(seen)[-10_000:])
        self.storage.add_audit(
            store_id,
            "connector_primed",
            connector.name,
            connector.name,
            {"primed": len(new_ids), "seen": len(seen)},
        )
        return {"connector": connector.name, "primed": len(new_ids), "seen": len(seen)}

    def run_operational_cycle(
        self, store_id: str, connector: EvidenceConnector
    ) -> dict[str, Any]:
        """Ingest newly discovered facts and route them through safe workflows."""

        ingestion = self.ingest_evidence_connector(store_id, connector)
        outcomes: list[dict[str, Any]] = []
        for evidence in ingestion["evidence"]:
            payload = evidence.get("payload", {})
            operation_type = payload.get("operation_type")
            common = {
                "product_id": payload.get("product_id"),
                "quantity": payload.get("quantity"),
                "mapping_verified": payload.get("mapping_verified", False),
                "source_record_hash": payload.get("source_record_hash"),
            }
            if operation_type == "purchase_line":
                facts = common | {
                    "pack_size": payload.get("pack_size"),
                    "destination_id": payload.get("destination_id"),
                    "receiver_confirmed": False,
                }
                outcomes.append(
                    self.process_event(
                        store_id,
                        EventType.RECEIVING,
                        facts,
                        [evidence["id"]],
                        occurred_at=evidence.get("occurred_at"),
                    )
                )
            elif operation_type == "sale_line":
                outcomes.append(
                    self.process_event(
                        store_id,
                        EventType.SALE,
                        common,
                        [evidence["id"]],
                        occurred_at=evidence.get("occurred_at"),
                    )
                )
        return {
            "connector": connector.name,
            "imported": ingestion["imported"],
            "events_created": len(outcomes),
            "outcomes": outcomes,
            "connector_errors": list(getattr(connector, "errors", [])),
        }

    def process_event(
        self,
        store_id: str,
        event_type: str,
        facts: dict[str, Any],
        evidence_ids: list[str] | None = None,
        occurred_at: str | None = None,
    ) -> dict[str, Any]:
        evidence_ids = evidence_ids or []
        unknown = [item for item in evidence_ids if not self.storage.get_record(item)]
        if unknown:
            raise ValueError(f"Unknown evidence references: {', '.join(unknown)}")
        event = OperationalEvent(
            store_id=store_id,
            event_type=EventType(event_type),
            facts=facts,
            evidence_ids=evidence_ids,
            **({"occurred_at": occurred_at} if occurred_at else {}),
        )
        result = self.workflows.evaluate(event)
        event.status = "verified" if not result.tasks else "needs_verification"
        self.storage.put_record("event", event.to_dict())
        for task in result.tasks:
            self.storage.put_record("task", task.to_dict())
        self.storage.add_audit(
            store_id,
            "event_evaluated",
            "jakasii",
            event.id,
            {"event_type": event_type, "tasks_created": len(result.tasks)},
        )
        if result.tasks:
            StoreMemory(self.data_root / "store-memory", store_id).append_exception(
                event.id, result.summary, evidence_ids
            )
        return {
            "event": event.to_dict(),
            "summary": result.summary,
            "tasks": [task.to_dict() for task in result.tasks],
        }

    def answer_task(
        self, store_id: str, task_id: str, answer: dict[str, Any], actor: str
    ) -> dict[str, Any]:
        task = self.storage.get_record(task_id)
        if not task or task.get("store_id") != store_id:
            raise KeyError(f"Unknown task: {task_id}")
        if task.get("status") != TaskStatus.OPEN:
            raise ValueError("Only open tasks can be answered.")
        confirmation = self.record_evidence(
            store_id,
            EvidenceKind.HUMAN_CONFIRMATION,
            actor,
            {"task_id": task_id, "answer": answer},
            1.0,
        )
        task["answer"] = answer | {"evidence_id": confirmation["id"], "actor": actor}
        task["status"] = TaskStatus.ANSWERED
        task["answered_at"] = utc_now()
        self.storage.put_record("task", task)
        self.storage.add_audit(
            store_id,
            "task_answered",
            actor,
            task_id,
            {"confirmation_evidence_id": confirmation["id"]},
        )
        return task

    def request_action(
        self,
        store_id: str,
        action: str,
        target: str,
        reason: str,
        authority: str,
        payload: dict[str, Any] | None = None,
        reversible: bool = False,
        data_leaving_device: bool = False,
    ) -> dict[str, Any]:
        from .models import AuthorityLevel

        request = ActionRequest(
            store_id=store_id,
            action=action,
            target=target,
            reason=reason,
            authority=AuthorityLevel(authority),
            payload=payload or {},
            reversible=reversible,
            data_leaving_device=data_leaving_device,
        )
        request = self.policy.classify(request)
        self.storage.put_record("action", request.to_dict())
        self.storage.add_audit(
            store_id,
            "action_requested",
            "jakasii",
            request.id,
            {"authority": authority, "status": request.status},
        )
        return request.to_dict()

    def approve_action(self, store_id: str, action_id: str, actor: str) -> dict[str, Any]:
        request = self.storage.get_record(action_id)
        if not request or request.get("store_id") != store_id:
            raise KeyError(f"Unknown action: {action_id}")
        request = self.policy.approve(request, actor)
        self.storage.put_record("action", request)
        self.storage.add_audit(store_id, "action_approved", actor, action_id, {})
        return request

    def mark_action_executed(
        self, store_id: str, action_id: str, result: dict[str, Any]
    ) -> dict[str, Any]:
        request = self.storage.get_record(action_id)
        if not request or request.get("store_id") != store_id:
            raise KeyError(f"Unknown action: {action_id}")
        if request.get("status") != "approved":
            raise PermissionError("Only an approved action can be marked executed.")
        request["status"] = "executed"
        request["executed_at"] = utc_now()
        request["execution_result"] = result
        self.storage.put_record("action", request)
        self.storage.add_audit(
            store_id,
            "action_executed",
            "jakasii_executor",
            action_id,
            {"state": result.get("state")},
        )
        return request

    def actions(self, store_id: str) -> list[dict[str, Any]]:
        return self.storage.list_records(store_id, "action")

    def readiness(self, store_id: str) -> dict[str, Any]:
        return self.onboarding.readiness(store_id).to_dict()

    def questions(self, store_id: str) -> list[dict[str, Any]]:
        return self.onboarding.questions(store_id)

    def tasks(self, store_id: str, open_only: bool = True) -> list[dict[str, Any]]:
        tasks = self.storage.list_records(store_id, "task")
        return [item for item in tasks if item.get("status") == TaskStatus.OPEN] if open_only else tasks

    def status(self, store_id: str) -> dict[str, Any]:
        return {
            "store_id": store_id,
            "provider": self.reasoner.name,
            "readiness": self.readiness(store_id),
            "open_questions": len(self.questions(store_id)),
            "open_tasks": len(self.tasks(store_id)),
            "events": len(self.storage.list_records(store_id, "event")),
            "evidence": len(self.storage.list_records(store_id, "evidence")),
            "actions": len(self.actions(store_id)),
            "agent": self.agent_status(store_id),
        }

    def memory(self, store_id: str) -> dict[str, str]:
        return StoreMemory(self.data_root / "store-memory", store_id).export_snapshot()

    def schema_catalog(self, store_id: str) -> dict[str, Any]:
        return self.storage.get_setting(store_id, "schema_catalog", {})

    def profile(self, store_id: str) -> dict[str, Any]:
        return self.storage.get_setting(store_id, "profile", {})

    def awareness(self, store_id: str) -> dict[str, Any]:
        return self.storage.get_setting(store_id, "awareness", {})

    def operational_snapshot(
        self, store_id: str, correlation_window_minutes: int = 15
    ) -> dict[str, Any]:
        snapshot = OperationalSnapshotEngine(correlation_window_minutes).build(
            store_id=store_id,
            readiness=self.readiness(store_id),
            evidence=self.storage.list_records(store_id, "evidence"),
            events=self.storage.list_records(store_id, "event"),
            tasks=self.tasks(store_id, open_only=False),
        )
        memory = StoreMemory(self.data_root / "store-memory", store_id)
        memory.write_json_artifact("Operational-Snapshot", snapshot)
        memory.write_operational_snapshot(snapshot)
        return snapshot

    def operation_proofs(
        self, store_id: str, correlation_window_minutes: int = 15
    ) -> dict[str, Any]:
        proofs = OperationProofEngine(correlation_window_minutes).build(
            store_id=store_id,
            evidence=self.storage.list_records(store_id, "evidence"),
            events=self.storage.list_records(store_id, "event"),
            tasks=self.tasks(store_id, open_only=False),
        )
        memory = StoreMemory(self.data_root / "store-memory", store_id)
        memory.write_json_artifact("Operation-Proofs", proofs)
        memory.write_operation_proofs(proofs)
        return proofs

    def agent_status(self, store_id: str) -> dict[str, Any]:
        return self.storage.get_setting(store_id, "agent:status", {})

    def audit(self, store_id: str) -> list[dict[str, Any]]:
        return self.storage.audit_log(store_id)

    def close(self) -> None:
        self.storage.close()
