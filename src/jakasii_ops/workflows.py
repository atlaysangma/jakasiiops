from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from .models import AuthorityLevel, EventType, OperationalEvent, VerificationTask


@dataclass(slots=True)
class WorkflowResult:
    event: OperationalEvent
    tasks: list[VerificationTask]
    summary: str


class WorkflowEngine:
    """Safety-first operational checks shared by every store connector."""

    def evaluate(self, event: OperationalEvent) -> WorkflowResult:
        handler: Callable[[OperationalEvent], WorkflowResult] = getattr(
            self, f"_check_{event.event_type.value}", self._check_generic
        )
        return handler(event)

    @staticmethod
    def _task(event: OperationalEvent, role: str, question: str, reason: str, official: bool = False) -> VerificationTask:
        return VerificationTask(
            store_id=event.store_id,
            role=role,
            question=question,
            reason=reason,
            related_event_id=event.id,
            required_authority=AuthorityLevel.OFFICIAL_RECORD if official else AuthorityLevel.EXTERNAL_REVERSIBLE,
        )

    def _check_receiving(self, event: OperationalEvent) -> WorkflowResult:
        facts = event.facts
        tasks: list[VerificationTask] = []
        if not facts.get("product_id"):
            tasks.append(self._task(event, "data_entry_operator", "Which SKU was received?", "Receiving evidence has no verified product identity."))
        if facts.get("cartons") is not None and not facts.get("pack_size"):
            tasks.append(self._task(event, "data_entry_operator", "What is the verified pieces-per-carton pack size?", "Cartons cannot become base units without pack size."))
        if not facts.get("destination_id"):
            tasks.append(self._task(event, "data_entry_operator", "Which godown or shelf received this product?", "Purchase entry has no physical destination."))
        if not facts.get("receiver_confirmed"):
            role = "shelfer" if facts.get("destination_type") == "shelf" else "godown_staff"
            tasks.append(self._task(event, role, "Confirm the quantity actually received at your location.", "DEO entry is not yet corroborated by the receiver.", official=True))
        summary = "Receiving reconciled" if not tasks else f"Receiving needs {len(tasks)} verification step(s)"
        return WorkflowResult(event, tasks, summary)

    def _check_stock_movement(self, event: OperationalEvent) -> WorkflowResult:
        facts = event.facts
        tasks: list[VerificationTask] = []
        if not facts.get("from_location") or not facts.get("to_location"):
            tasks.append(self._task(event, "godown_staff", "Confirm both source and destination locations.", "Movement route is incomplete."))
        sent = facts.get("sent_quantity")
        received = facts.get("received_quantity")
        if sent is None:
            tasks.append(self._task(event, "godown_staff", "How many base units left the source location?", "Movement has no sender quantity."))
        if received is None:
            tasks.append(self._task(event, "shelfer", "How many base units arrived at the shelf?", "Movement has no receiver confirmation.", official=True))
        elif sent is not None and sent != received:
            tasks.append(self._task(event, "manager", f"Resolve movement mismatch: sent {sent}, received {received}.", "Sender and receiver records conflict.", official=True))
        summary = "Stock movement reconciled" if not tasks else f"Stock movement needs {len(tasks)} verification step(s)"
        return WorkflowResult(event, tasks, summary)

    def _check_damage(self, event: OperationalEvent) -> WorkflowResult:
        tasks: list[VerificationTask] = []
        if not event.facts.get("quantity"):
            tasks.append(self._task(event, "godown_staff", "Count the damaged base units.", "Damage observation has no verified quantity."))
        if not event.facts.get("human_confirmed"):
            tasks.append(self._task(event, "manager", "Review and approve this damage adjustment.", "Camera or staff observation cannot alter stock by itself.", official=True))
        return WorkflowResult(event, tasks, "Damage verified" if not tasks else f"Damage needs {len(tasks)} verification step(s)")

    def _check_expiry(self, event: OperationalEvent) -> WorkflowResult:
        tasks = [] if event.facts.get("human_confirmed") else [
            self._task(event, "manager", "Confirm the batch, expiry date, quantity, and disposition.", "Expiry requires a traceable human decision.", official=True)
        ]
        return WorkflowResult(event, tasks, "Expiry verified" if not tasks else "Expiry needs manager verification")

    def _check_attendance(self, event: OperationalEvent) -> WorkflowResult:
        facts = event.facts
        tasks: list[VerificationTask] = []
        if not facts.get("staff_id") and not facts.get("badge_id"):
            tasks.append(self._task(event, "manager", "Identify this attendance observation using an approved badge or staff record.", "Uniform/camera evidence alone is not official attendance."))
        if facts.get("source") == "camera" and not facts.get("human_confirmed"):
            tasks.append(self._task(event, "manager", "Confirm attendance before recording it officially.", "Camera presence is supporting evidence only.", official=True))
        return WorkflowResult(event, tasks, "Attendance corroborated" if not tasks else f"Attendance needs {len(tasks)} verification step(s)")

    def _check_sale(self, event: OperationalEvent) -> WorkflowResult:
        facts = event.facts
        tasks: list[VerificationTask] = []
        if not facts.get("product_id") or facts.get("quantity") is None:
            tasks.append(self._task(event, "data_entry_operator", "Repair the sale line with a product and base-unit quantity.", "POS sale record is incomplete."))
        if facts.get("stock_after") is not None and facts["stock_after"] < 0:
            tasks.append(self._task(event, "shelfer", "Recount shelf stock for this SKU.", "The recorded sale produced negative stock."))
        return WorkflowResult(event, tasks, "Sale reconciled" if not tasks else f"Sale needs {len(tasks)} verification step(s)")

    def _check_purchase(self, event: OperationalEvent) -> WorkflowResult:
        tasks = []
        if event.facts.get("cartons") is not None and not event.facts.get("pack_size"):
            tasks.append(self._task(event, "data_entry_operator", "Confirm pack size for this purchase line.", "Carton quantity is ambiguous."))
        return WorkflowResult(event, tasks, "Purchase normalized" if not tasks else "Purchase needs pack conversion")

    def _check_return(self, event: OperationalEvent) -> WorkflowResult:
        tasks = [] if event.facts.get("approved") else [
            self._task(event, "manager", "Approve the return and its stock effect.", "Returns change official stock and value.", official=True)
        ]
        return WorkflowResult(event, tasks, "Return approved" if not tasks else "Return awaits approval")

    def _check_stock_count(self, event: OperationalEvent) -> WorkflowResult:
        expected = event.facts.get("expected_quantity")
        counted = event.facts.get("counted_quantity")
        tasks: list[VerificationTask] = []
        if counted is None:
            tasks.append(self._task(event, "godown_staff", "Count this SKU in base units.", "No physical count was recorded."))
        elif expected is not None and counted != expected:
            tasks.append(self._task(event, "manager", f"Review stock variance: system {expected}, physical {counted}.", "Physical count conflicts with the system record.", official=True))
        return WorkflowResult(event, tasks, "Stock count reconciled" if not tasks else f"Stock count needs {len(tasks)} verification step(s)")

    def _check_generic(self, event: OperationalEvent) -> WorkflowResult:
        task = self._task(event, "manager", "Review this unsupported operational event.", "No approved workflow is configured for this event type.")
        return WorkflowResult(event, [task], "Unsupported event routed to manager")

