from __future__ import annotations

from pathlib import Path
from typing import Any

from .actions import ActionRequest, PolicyGate
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
from .reasoning import DeterministicReasoner, ReasoningProvider
from .storage import OpsStore
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
    ) -> dict[str, Any]:
        evidence = Evidence(
            kind=EvidenceKind(kind),
            source=source,
            payload=payload,
            store_id=store_id,
            confidence=max(0.0, min(float(confidence), 1.0)),
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

    def process_event(
        self,
        store_id: str,
        event_type: str,
        facts: dict[str, Any],
        evidence_ids: list[str] | None = None,
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
        }

    def memory(self, store_id: str) -> dict[str, str]:
        return StoreMemory(self.data_root / "store-memory", store_id).export_snapshot()

    def audit(self, store_id: str) -> list[dict[str, Any]]:
        return self.storage.audit_log(store_id)

    def close(self) -> None:
        self.storage.close()
