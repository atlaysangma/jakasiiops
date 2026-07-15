from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import StrEnum
from typing import Any

from .models import AuthorityLevel, new_id, utc_now


class ActionStatus(StrEnum):
    ALLOWED = "allowed"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    DENIED = "denied"
    EXECUTED = "executed"


@dataclass(slots=True)
class ActionRequest:
    store_id: str
    action: str
    target: str
    reason: str
    authority: AuthorityLevel
    payload: dict[str, Any] = field(default_factory=dict)
    reversible: bool = False
    data_leaving_device: bool = False
    status: ActionStatus = ActionStatus.PENDING_APPROVAL
    created_at: str = field(default_factory=utc_now)
    id: str = field(default_factory=lambda: new_id("action"))

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PolicyGate:
    """Makes authority explicit before any future connector executes a hand."""

    AUTOMATIC = {AuthorityLevel.OBSERVE, AuthorityLevel.LOCAL_WORK}

    def classify(self, request: ActionRequest) -> ActionRequest:
        if request.authority == AuthorityLevel.PROHIBITED:
            request.status = ActionStatus.DENIED
        elif request.authority in self.AUTOMATIC:
            request.status = ActionStatus.ALLOWED
        else:
            request.status = ActionStatus.PENDING_APPROVAL
        return request

    def approve(self, request: dict[str, Any], actor: str) -> dict[str, Any]:
        if request["status"] == ActionStatus.DENIED:
            raise PermissionError("Prohibited actions cannot be approved.")
        if request["status"] not in (ActionStatus.PENDING_APPROVAL, ActionStatus.ALLOWED):
            raise ValueError("Action is not awaiting approval.")
        request["status"] = ActionStatus.APPROVED
        request["approved_by"] = actor
        request["approved_at"] = utc_now()
        return request

