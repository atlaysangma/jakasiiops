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

    def write_awareness(self, awareness: dict[str, Any]) -> Path:
        folder = self.root / "Learning"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "Store-Awareness.md"
        lines = [
            "---",
            f"store_id: {self.store_id}",
            f"generated: {awareness.get('generated_at')}",
            "verified: false",
            "source: structural-metadata-only",
            "---",
            "",
            "# Store Awareness",
            "",
            "This is JAKASII's current hypothesis, not an approved business truth.",
            "",
            f"- Sources inspected: **{len(awareness.get('sources', []))}**",
            f"- Tables discovered: **{awareness.get('table_count', 0)}**",
            f"- Columns discovered: **{awareness.get('column_count', 0)}**",
            f"- Camera channels discovered: **{awareness.get('camera_channel_count', 0)}**",
            f"- Declared relationships: **{len(awareness.get('declared_relationships', []))}**",
            f"- Candidate relationships: **{len(awareness.get('inferred_relationships', []))}**",
            "",
            "## Capabilities observed",
            "",
        ]
        capabilities = awareness.get("capabilities_observed", [])
        lines.extend(f"- `{item}`" for item in capabilities)
        if not capabilities:
            lines.append("- None yet")
        lines.extend(["", "## Unresolved concepts", ""])
        unknowns = awareness.get("unknowns", [])
        lines.extend(f"- [ ] `{item}`" for item in unknowns)
        if not unknowns:
            lines.append("- None")
        lines.extend(["", "## Leading structural hypotheses", ""])
        for role, candidates in sorted(awareness.get("role_candidates", {}).items()):
            if not candidates:
                continue
            leading = candidates[0]
            lines.append(
                f"- `{role}` ← `{leading['source_path']}` "
                f"(unverified, confidence {leading['confidence']:.2f})"
            )
        lines.extend(
            [
                "",
                "## Next safe step",
                "",
                awareness.get(
                    "next_safe_step",
                    "Confirm structural hypotheses before reading business rows.",
                ),
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

    def write_operational_snapshot(self, snapshot: dict[str, Any]) -> Path:
        folder = self.root / "Learning"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "Operational-Snapshot.md"
        lines = [
            "---",
            f"store_id: {self.store_id}",
            f"generated: {snapshot.get('generated_at')}",
            f"state: {snapshot.get('state')}",
            "---",
            "",
            "# Operational Snapshot",
            "",
            "## What JAKASII currently sees",
            "",
        ]
        for kind, count in snapshot.get("evidence_counts", {}).items():
            lines.append(f"- `{kind}` evidence: **{count}**")
        lines.extend(["", "## Open work", ""])
        roles = snapshot.get("open_tasks_by_role", {})
        lines.extend(f"- `{role}`: **{count}**" for role, count in roles.items())
        if not roles:
            lines.append("- No open verification tasks")
        correlation = snapshot.get("correlation", {})
        lines.extend(
            [
                "",
                "## Cross-source coverage",
                "",
                f"- Temporally matched system records: **{correlation.get('corroborated_system_records', 0)}**",
                f"- System records without nearby camera evidence: **{correlation.get('uncorroborated_system_records', 0)}**",
                f"- Unlinked camera observations: **{correlation.get('unlinked_observations', 0)}**",
                "- Camera timing is supporting context, never physical verification by itself.",
                "",
                "## Attention",
                "",
            ]
        )
        attention = snapshot.get("attention", [])
        lines.extend(f"- {item}" for item in attention)
        if not attention:
            lines.append("- No unresolved attention items")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        return path

    def write_operation_proofs(self, report: dict[str, Any]) -> Path:
        folder = self.root / "Learning"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / "Operation-Proofs.md"
        lines = [
            "---",
            f"store_id: {self.store_id}",
            f"generated: {report.get('generated_at')}",
            f"complete_count: {report.get('complete_count', 0)}",
            "---",
            "",
            "# Real Operation Proofs",
            "",
            report.get("proof_definition", ""),
            "",
        ]
        for proof in report.get("proofs", []):
            lines.extend(
                [
                    f"## {proof.get('event_type')} — `{proof.get('event_id')}`",
                    "",
                    f"- State: **{proof.get('state')}**",
                    f"- Occurred: {proof.get('occurred_at')}",
                    f"- Database evidence: **{len(proof.get('system_evidence_ids', []))}**",
                    f"- Nearby camera context: **{'yes' if proof.get('camera_observation_id') else 'no'}**",
                    f"- Positive role confirmation: **{'yes' if proof.get('positive_confirmation_task_ids') else 'no'}**",
                    "- Camera identifies SKU/quantity: **no**",
                    "- JAKASII wrote an official record: **no**",
                    "",
                ]
            )
        if not report.get("proofs"):
            lines.append("No operational event has been observed yet.")
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
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
