from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import StrEnum
from typing import Any
from uuid import uuid4


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class EvidenceKind(StrEnum):
    OBSERVATION = "observation"
    SYSTEM_RECORD = "system_record"
    HUMAN_CONFIRMATION = "human_confirmation"
    MANAGER_DECISION = "manager_decision"


class EventType(StrEnum):
    RECEIVING = "receiving"
    STOCK_MOVEMENT = "stock_movement"
    DAMAGE = "damage"
    EXPIRY = "expiry"
    ATTENDANCE = "attendance"
    SALE = "sale"
    PURCHASE = "purchase"
    RETURN = "return"
    STOCK_COUNT = "stock_count"


class TaskStatus(StrEnum):
    OPEN = "open"
    ANSWERED = "answered"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLOSED = "closed"


class AuthorityLevel(StrEnum):
    OBSERVE = "observe"
    LOCAL_WORK = "local_work"
    EXTERNAL_REVERSIBLE = "external_reversible"
    SYSTEM_CHANGE = "system_change"
    OFFICIAL_RECORD = "official_record"
    PROHIBITED = "prohibited"


@dataclass(slots=True)
class Evidence:
    kind: EvidenceKind
    source: str
    payload: dict[str, Any]
    store_id: str
    confidence: float = 1.0
    occurred_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: new_id("evd"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class OperationalEvent:
    store_id: str
    event_type: EventType
    facts: dict[str, Any]
    evidence_ids: list[str]
    status: str = "observed"
    occurred_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: new_id("evt"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class VerificationTask:
    store_id: str
    role: str
    question: str
    reason: str
    related_event_id: str
    required_authority: AuthorityLevel = AuthorityLevel.EXTERNAL_REVERSIBLE
    status: TaskStatus = TaskStatus.OPEN
    answer: dict[str, Any] | None = None
    created_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: new_id("task"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class SetupQuestion:
    store_id: str
    key: str
    prompt: str
    reason: str
    options: list[str] = field(default_factory=list)
    answer: Any | None = None
    resolved: bool = False
    created_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: new_id("question"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class Mapping:
    canonical_field: str
    source_path: str
    confidence: float
    reasoning: str
    verified: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReadinessCheck:
    key: str
    label: str
    passed: bool
    detail: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(slots=True)
class ReadinessReport:
    store_id: str
    checks: list[ReadinessCheck]
    unresolved_questions: int
    authority: list[AuthorityLevel]
    generated_at: str = field(default_factory=utc_now)

    @property
    def ready(self) -> bool:
        return all(check.passed for check in self.checks) and self.unresolved_questions == 0

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["ready"] = self.ready
        return data

