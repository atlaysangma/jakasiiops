from __future__ import annotations

from typing import Any, Iterable, Protocol


class SchemaConnector(Protocol):
    """Read-only discovery surface for SQL, files, APIs and app databases."""

    name: str

    def inspect_schema(self) -> dict[str, Any]: ...

    def sample_records(self, table: str, limit: int = 5) -> list[dict[str, Any]]: ...


class EvidenceConnector(Protocol):
    """Camera/event/POS adapters emit evidence; they do not mutate business facts."""

    name: str

    def poll(self) -> Iterable[dict[str, Any]]: ...


class TaskSink(Protocol):
    """Existing staff/boss apps consume verification work through this boundary."""

    name: str

    def deliver(self, task: dict[str, Any]) -> str: ...


class ActionExecutor(Protocol):
    """A future hand must receive an already approved action request."""

    name: str

    def execute(self, approved_action: dict[str, Any]) -> dict[str, Any]: ...

