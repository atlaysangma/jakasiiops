from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from .models import ReadinessReport, utc_now


class StoreMemory:
    """Obsidian-compatible explainable memory; exact state remains in SQLite."""

    SECTIONS = (
        "Store.md",
        "Products.md",
        "Locations.md",
        "Cameras.md",
        "Staff-Roles.md",
        "Workflows.md",
        "Policies.md",
        "Known-Problems.md",
    )

    def __init__(self, root: str | Path, store_id: str) -> None:
        self.root = Path(root) / store_id
        self.store_id = store_id

    def initialize(self, store_name: str) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        for folder in ("Daily-Operations", "Exceptions", "Decisions", "Learning"):
            (self.root / folder).mkdir(exist_ok=True)
        for filename in self.SECTIONS:
            path = self.root / filename
            if not path.exists():
                title = filename.removesuffix(".md").replace("-", " ")
                path.write_text(
                    "---\n"
                    f"store_id: {self.store_id}\n"
                    f"created: {utc_now()}\n"
                    "source: jakasii-ops\n"
                    "---\n\n"
                    f"# {title}\n\n"
                    f"Part of [[Store]] for {store_name}.\n",
                    encoding="utf-8",
                )

    def write_store_profile(self, profile: dict[str, Any]) -> Path:
        self.initialize(profile.get("name", self.store_id))
        mappings = profile.get("mappings", [])
        lines = [
            "---",
            f"store_id: {self.store_id}",
            f"updated: {utc_now()}",
            "source: jakasii-ops",
            "---",
            "",
            f"# {profile.get('name', self.store_id)}",
            "",
            "## Connected sources",
            "",
        ]
        lines.extend(f"- {source}" for source in profile.get("sources", []))
        lines.extend(["", "## Verified mappings", ""])
        for mapping in mappings:
            mark = "verified" if mapping.get("verified") else "proposed"
            lines.append(
                f"- `{mapping['canonical_field']}` ← `{mapping['source_path']}` "
                f"({mark}, confidence {mapping['confidence']:.2f})"
            )
        lines.extend(
            [
                "",
                "## Operational links",
                "",
                "- [[Products]]",
                "- [[Locations]]",
                "- [[Cameras]]",
                "- [[Staff-Roles]]",
                "- [[Workflows]]",
                "- [[Policies]]",
                "- [[Known-Problems]]",
            ]
        )
        path = self.root / "Store.md"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def write_readiness(self, report: ReadinessReport) -> Path:
        folder = self.root / "Learning"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "Readiness.md"
        lines = [
            "---",
            f"store_id: {self.store_id}",
            f"generated: {report.generated_at}",
            f"ready: {str(report.ready).lower()}",
            "---",
            "",
            "# Readiness",
            "",
        ]
        for check in report.checks:
            lines.append(f"- [{'x' if check.passed else ' '}] {check.label} — {check.detail}")
        lines.extend(
            [
                "",
                f"Unresolved setup questions: **{report.unresolved_questions}**",
                f"Authority: {', '.join(str(item) for item in report.authority)}",
                "",
                "Exact mappings and events remain in the structured audit database.",
            ]
        )
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def append_exception(self, event_id: str, summary: str, evidence_ids: list[str]) -> Path:
        folder = self.root / "Exceptions"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{event_id}.md"
        path.write_text(
            "---\n"
            f"store_id: {self.store_id}\n"
            f"event_id: {event_id}\n"
            f"created: {utc_now()}\n"
            "---\n\n"
            f"# Operational exception {event_id}\n\n{summary}\n\n"
            "## Evidence references\n\n"
            + "\n".join(f"- `{item}`" for item in evidence_ids)
            + "\n",
            encoding="utf-8",
        )
        return path

    def export_snapshot(self) -> dict[str, str]:
        if not self.root.exists():
            return {}
        return {
            path.relative_to(self.root).as_posix(): path.read_text(encoding="utf-8")
            for path in self.root.rglob("*.md")
        }

    def write_json_artifact(self, name: str, payload: dict[str, Any]) -> Path:
        path = self.root / "Learning" / f"{name}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return path
