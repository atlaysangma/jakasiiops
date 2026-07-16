from __future__ import annotations

from collections import Counter
from datetime import datetime
from typing import Any

from .models import utc_now


class OperationalSnapshotEngine:
    """Summarize what the store brain knows without merging evidence truth."""

    def __init__(self, correlation_window_minutes: int = 15) -> None:
        self.window_seconds = max(1, correlation_window_minutes) * 60
        self.local_timezone = datetime.now().astimezone().tzinfo

    def _timestamp(self, value: Any) -> datetime | None:
        text = str(value or "").strip()
        if not text or text == "unknown":
            return None
        try:
            parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None and self.local_timezone is not None:
            parsed = parsed.replace(tzinfo=self.local_timezone)
        return parsed

    def build(
        self,
        store_id: str,
        readiness: dict[str, Any],
        evidence: list[dict[str, Any]],
        events: list[dict[str, Any]],
        tasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        by_kind = Counter(str(item.get("kind", "unknown")) for item in evidence)
        by_source: dict[str, dict[str, Any]] = {}
        for item in evidence:
            source = str(item.get("source", "unknown"))
            state = by_source.setdefault(
                source,
                {"source": source, "count": 0, "kinds": set(), "latest_at": None},
            )
            state["count"] += 1
            state["kinds"].add(str(item.get("kind", "unknown")))
            current = self._timestamp(item.get("occurred_at"))
            latest = self._timestamp(state["latest_at"])
            if current and (latest is None or current > latest):
                state["latest_at"] = item.get("occurred_at")

        observations = [item for item in evidence if item.get("kind") == "observation"]
        system_records = [item for item in evidence if item.get("kind") == "system_record"]
        correlations: list[dict[str, Any]] = []
        correlated_system_ids: set[str] = set()
        correlated_observation_ids: set[str] = set()
        for system in system_records:
            system_time = self._timestamp(system.get("occurred_at"))
            if not system_time:
                continue
            nearest: tuple[float, dict[str, Any]] | None = None
            for observation in observations:
                observation_time = self._timestamp(observation.get("occurred_at"))
                if not observation_time:
                    continue
                difference = abs((system_time - observation_time).total_seconds())
                if nearest is None or difference < nearest[0]:
                    nearest = (difference, observation)
            if nearest and nearest[0] <= self.window_seconds:
                observation = nearest[1]
                correlated_system_ids.add(str(system.get("id")))
                correlated_observation_ids.add(str(observation.get("id")))
                correlations.append(
                    {
                        "system_record_id": system.get("id"),
                        "observation_id": observation.get("id"),
                        "time_difference_seconds": round(nearest[0], 1),
                        "claim": "temporal_cooccurrence_only",
                        "verified": False,
                    }
                )

        latest_system = max(
            (self._timestamp(item.get("occurred_at")) for item in system_records),
            default=None,
            key=lambda item: item or datetime.min.replace(tzinfo=self.local_timezone),
        )
        latest_observation = max(
            (self._timestamp(item.get("occurred_at")) for item in observations),
            default=None,
            key=lambda item: item or datetime.min.replace(tzinfo=self.local_timezone),
        )
        gap_hours = None
        if latest_system and latest_observation:
            gap_hours = round(abs((latest_observation - latest_system).total_seconds()) / 3600, 2)

        open_tasks = [item for item in tasks if item.get("status") == "open"]
        attention: list[str] = []
        if not readiness.get("ready"):
            attention.append(
                f"Store setup has {readiness.get('unresolved_questions', 0)} unresolved confirmation(s)."
            )
        uncorroborated = len(system_records) - len(correlated_system_ids)
        if uncorroborated:
            attention.append(
                f"{uncorroborated} system record(s) have no camera observation within the configured time window."
            )
        if open_tasks:
            roles = Counter(str(item.get("role", "unknown")) for item in open_tasks)
            attention.append(
                "Open verification work: "
                + ", ".join(f"{role}={count}" for role, count in sorted(roles.items()))
                + "."
            )

        return {
            "store_id": store_id,
            "generated_at": utc_now(),
            "state": "needs_attention" if attention else "clear",
            "readiness": {
                "ready": bool(readiness.get("ready")),
                "unresolved_questions": int(readiness.get("unresolved_questions", 0)),
            },
            "evidence_counts": dict(sorted(by_kind.items())),
            "last_seen_by_source": [
                {
                    **{key: value for key, value in state.items() if key != "kinds"},
                    "kinds": sorted(state["kinds"]),
                }
                for state in sorted(by_source.values(), key=lambda item: item["source"])
            ],
            "event_counts": dict(
                sorted(Counter(str(item.get("event_type", "unknown")) for item in events).items())
            ),
            "event_status_counts": dict(
                sorted(Counter(str(item.get("status", "unknown")) for item in events).items())
            ),
            "open_tasks_by_role": dict(
                sorted(Counter(str(item.get("role", "unknown")) for item in open_tasks).items())
            ),
            "correlation": {
                "window_minutes": self.window_seconds // 60,
                "timezone_assumption": "naive_source_timestamps_use_host_local_offset",
                "matches": correlations,
                "corroborated_system_records": len(correlated_system_ids),
                "uncorroborated_system_records": uncorroborated,
                "unlinked_observations": len(observations) - len(correlated_observation_ids),
                "latest_source_gap_hours": gap_hours,
                "camera_cooccurrence_is_not_physical_verification": True,
            },
            "attention": attention,
        }
