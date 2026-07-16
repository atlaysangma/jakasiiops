from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .models import utc_now


OPERATIONAL_CONFIRMATION_ROLES = {
    "data_entry_operator",
    "deo",
    "godown_staff",
    "godown_incharge",
    "shelfer",
    "receiver",
}


class OperationProofEngine:
    """Assemble strict proof state without turning camera timing into stock truth."""

    def __init__(self, correlation_window_minutes: int = 15) -> None:
        self.window_seconds = max(1, correlation_window_minutes) * 60
        self.local_timezone = datetime.now().astimezone().tzinfo

    def _timestamp(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text:
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None and self.local_timezone is not None:
            parsed = parsed.replace(tzinfo=self.local_timezone)
        return parsed

    @staticmethod
    def _is_camera_observation(evidence: dict[str, Any]) -> bool:
        if evidence.get("kind") != "observation":
            return False
        source = str(evidence.get("source", "")).lower()
        return any(token in source for token in ("camera", "cctv", "vision"))

    @staticmethod
    def _confirmation_value(answer: dict[str, Any]) -> bool | None:
        for key in ("confirmed", "verified", "matches_record", "received", "completed"):
            if key in answer:
                value = answer[key]
                if isinstance(value, bool):
                    return value
                normalized = str(value).strip().lower()
                if normalized in {"yes", "true", "confirmed", "verified", "received", "complete"}:
                    return True
                if normalized in {"no", "false", "rejected", "mismatch", "missing"}:
                    return False
        return None

    def _nearest_camera(
        self, event: dict[str, Any], observations: list[dict[str, Any]]
    ) -> tuple[dict[str, Any] | None, float | None]:
        event_time = self._timestamp(event.get("occurred_at"))
        if not event_time:
            return None, None
        nearest: tuple[float, dict[str, Any]] | None = None
        for observation in observations:
            observed_at = self._timestamp(observation.get("occurred_at"))
            if not observed_at:
                continue
            difference = abs((event_time - observed_at).total_seconds())
            if difference <= self.window_seconds and (
                nearest is None or difference < nearest[0]
            ):
                nearest = (difference, observation)
        if nearest is None:
            return None, None
        return nearest[1], round(nearest[0], 1)

    def build(
        self,
        store_id: str,
        evidence: list[dict[str, Any]],
        events: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        evidence_by_id = {str(item.get("id")): item for item in evidence}
        observations = [item for item in evidence if self._is_camera_observation(item)]
        tasks_by_event: dict[str, list[dict[str, Any]]] = {}
        for task in tasks:
            tasks_by_event.setdefault(str(task.get("related_event_id", "")), []).append(task)

        proofs: list[dict[str, Any]] = []
        for event in events:
            event_id = str(event.get("id", ""))
            linked = [
                evidence_by_id[item]
                for item in event.get("evidence_ids", [])
                if item in evidence_by_id
            ]
            system_records = [item for item in linked if item.get("kind") == "system_record"]
            camera, time_difference = self._nearest_camera(event, observations)
            event_tasks = tasks_by_event.get(event_id, [])
            positive: list[dict[str, Any]] = []
            negative: list[dict[str, Any]] = []
            for task in event_tasks:
                if task.get("status") != "answered" or task.get("role") not in OPERATIONAL_CONFIRMATION_ROLES:
                    continue
                answer = task.get("answer") or {}
                confirmation = evidence_by_id.get(str(answer.get("evidence_id", "")))
                if not confirmation or confirmation.get("kind") != "human_confirmation":
                    continue
                value = self._confirmation_value(answer)
                if value is True:
                    positive.append(task)
                elif value is False:
                    negative.append(task)

            missing: list[str] = []
            if not system_records:
                missing.append("linked_system_record")
            if camera is None:
                missing.append("nearby_camera_observation")
            if not positive:
                missing.append("positive_role_routed_confirmation")

            if negative:
                state = "disputed"
            elif not system_records:
                state = "awaiting_system_record"
            elif camera is None:
                state = "awaiting_camera_context"
            elif not positive:
                state = "awaiting_human_confirmation"
            else:
                state = "evidence_complete"

            proofs.append(
                {
                    "event_id": event_id,
                    "event_type": event.get("event_type"),
                    "occurred_at": event.get("occurred_at"),
                    "state": state,
                    "system_evidence_ids": [item.get("id") for item in system_records],
                    "camera_observation_id": camera.get("id") if camera else None,
                    "camera_time_difference_seconds": time_difference,
                    "positive_confirmation_task_ids": [item.get("id") for item in positive],
                    "negative_confirmation_task_ids": [item.get("id") for item in negative],
                    "missing": missing,
                    "claims": {
                        "database_record_present": bool(system_records),
                        "camera_temporal_context_present": camera is not None,
                        "role_routed_human_confirmation_present": bool(positive),
                        "camera_identified_product_or_quantity": False,
                        "official_business_record_written_by_jakasii": False,
                    },
                }
            )

        state_counts = Counter(item["state"] for item in proofs)
        return {
            "store_id": store_id,
            "generated_at": utc_now(),
            "proof_definition": (
                "A linked database record, nearby camera timing context, and a positive "
                "role-routed human confirmation. Camera timing never proves SKU or quantity."
            ),
            "window_minutes": self.window_seconds // 60,
            "state_counts": dict(sorted(state_counts.items())),
            "complete_count": state_counts.get("evidence_complete", 0),
            "proofs": proofs,
        }
