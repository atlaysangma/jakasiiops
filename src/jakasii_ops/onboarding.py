from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .memory import StoreMemory
from .models import (
    AuthorityLevel,
    Mapping,
    ReadinessCheck,
    ReadinessReport,
    SetupQuestion,
)
from .reasoning import DeterministicReasoner, ReasoningProvider
from .storage import OpsStore


CANONICAL_FIELDS: dict[str, dict[str, Any]] = {
    "product.identity": {
        "tokens": ("productid", "productcode", "itemcode", "sku", "pcode", "prodid"),
        "required": True,
        "label": "Product/SKU identity",
    },
    "purchase.quantity": {
        "tokens": ("quantity", "qty", "pieces", "pcs", "purchaseqty", "receivedqty"),
        "required": True,
        "label": "Purchase/receiving quantity",
    },
    "product.pack_size": {
        "tokens": ("packsize", "unitspercase", "pcspercarton", "conversion", "packing", "factor"),
        "required": True,
        "label": "Carton/pack/piece conversion",
    },
    "movement.destination": {
        "tokens": ("destination", "destinationid", "dest", "godown", "warehouse", "location", "locationid"),
        "required": True,
        "label": "Godown/shelf destination",
    },
    "camera.zone": {
        "tokens": ("camerazone", "cameraid", "channel", "camchannel", "zone", "streamid"),
        "required": True,
        "label": "Camera channel and monitored zone",
    },
    "staff.role": {
        "tokens": ("staffrole", "role", "designation", "duty", "jobtitle"),
        "required": True,
        "label": "DEO/staff task routing",
    },
    "sale.quantity": {
        "tokens": ("saleqty", "soldqty", "unitsold", "billqty"),
        "required": False,
        "label": "POS sale quantity",
    },
    "damage.quantity": {
        "tokens": ("damageqty", "damagedunits", "wastage", "brokenqty"),
        "required": False,
        "label": "Damage quantity",
    },
    "attendance.identity": {
        "tokens": ("badgeid", "staffid", "employeeid", "attendanceid"),
        "required": False,
        "label": "Attendance identity",
    },
}


def normalize_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


class SchemaDiscovery:
    """Reads exported schema metadata only; production connectors plug in here."""

    def load(self, path: str | Path) -> dict[str, Any]:
        source_path = Path(path)
        document = json.loads(source_path.read_text(encoding="utf-8"))
        required = {"store_id", "name", "sources"}
        missing = required - set(document)
        if missing:
            raise ValueError(f"Schema document is missing: {', '.join(sorted(missing))}")
        document["schema_file"] = str(source_path.resolve())
        return document

    def flatten_columns(self, document: dict[str, Any]) -> list[dict[str, Any]]:
        columns: list[dict[str, Any]] = []
        for source in document.get("sources", []):
            for table in source.get("tables", []):
                for column in table.get("columns", []):
                    path = f"{source['name']}.{table['name']}.{column['name']}"
                    columns.append(
                        {
                            "path": path,
                            "normalized": normalize_name(column["name"]),
                            "type": column.get("type", "unknown"),
                            "samples": column.get("samples", [])[:5],
                        }
                    )
        return columns


class MappingEngine:
    def __init__(self, reasoner: ReasoningProvider | None = None) -> None:
        self.reasoner = reasoner or DeterministicReasoner()

    @staticmethod
    def _score(column: dict[str, Any], tokens: tuple[str, ...]) -> float:
        name = column["normalized"]
        if name in tokens:
            return 0.98
        if any(token in name or name in token for token in tokens):
            return 0.86
        token_parts = set(re.findall(r"[a-z]+", column["path"].lower()))
        if any(token in token_parts for token in tokens):
            return 0.72
        return 0.0

    def propose(self, document: dict[str, Any]) -> list[Mapping]:
        columns = SchemaDiscovery().flatten_columns(document)
        mappings: list[Mapping] = []
        for canonical, config in CANONICAL_FIELDS.items():
            ranked = sorted(
                ((self._score(column, config["tokens"]), column) for column in columns),
                key=lambda item: item[0],
                reverse=True,
            )
            ranked = [item for item in ranked if item[0] > 0]
            if not ranked:
                continue
            best_score, best = ranked[0]
            reasoning = "Matched normalized column name and canonical vocabulary."
            if best_score < 0.8:
                candidates = [item[1]["path"] for item in ranked[:5]]
                selected, model_score, model_reason = self.reasoner.choose_mapping(
                    canonical, candidates, {"columns": columns}
                )
                if selected:
                    best = next(column for column in columns if column["path"] == selected)
                    best_score = max(best_score, model_score)
                    reasoning = model_reason
            mappings.append(
                Mapping(
                    canonical_field=canonical,
                    source_path=best["path"],
                    confidence=round(best_score, 2),
                    reasoning=reasoning,
                    verified=best_score >= 0.95,
                )
            )
        return mappings


class OnboardingEngine:
    def __init__(
        self,
        storage: OpsStore,
        memory_root: str | Path,
        reasoner: ReasoningProvider | None = None,
    ) -> None:
        self.storage = storage
        self.memory_root = Path(memory_root)
        self.discovery = SchemaDiscovery()
        self.mapper = MappingEngine(reasoner)

    def start(self, schema_path: str | Path) -> dict[str, Any]:
        document = self.discovery.load(schema_path)
        store_id = document["store_id"]
        mappings = self.mapper.propose(document)
        questions: list[SetupQuestion] = []
        mapped_fields = {mapping.canonical_field for mapping in mappings}

        for canonical, config in CANONICAL_FIELDS.items():
            if not config["required"]:
                continue
            mapping = next((item for item in mappings if item.canonical_field == canonical), None)
            if mapping is None:
                questions.append(
                    SetupQuestion(
                        store_id=store_id,
                        key=f"map:{canonical}",
                        prompt=f"Which source field represents {config['label'].lower()}?",
                        reason="JAKASII could not infer this required meaning safely.",
                    )
                )
            elif not mapping.verified:
                questions.append(
                    SetupQuestion(
                        store_id=store_id,
                        key=f"verify:{canonical}",
                        prompt=f"Does `{mapping.source_path}` represent {config['label'].lower()}?",
                        reason=f"Proposed at confidence {mapping.confidence:.2f}; important meanings require confirmation.",
                        options=[mapping.source_path, "none_of_these"],
                    )
                )

        profile = {
            "store_id": store_id,
            "name": document["name"],
            "sources": [source["name"] for source in document["sources"]],
            "schema_file": document["schema_file"],
            "mappings": [mapping.to_dict() for mapping in mappings],
            "discovered_fields": sorted(mapped_fields),
        }
        self.storage.set_setting(store_id, "profile", profile)
        for question in questions:
            self.storage.put_record("setup_question", question.to_dict())
        self.storage.add_audit(
            store_id,
            "onboarding_started",
            "jakasii",
            "store_profile",
            {"mappings": len(mappings), "questions": len(questions)},
        )
        memory = StoreMemory(self.memory_root, store_id)
        memory.write_store_profile(profile)
        report = self.readiness(store_id)
        memory.write_readiness(report)
        return {"profile": profile, "questions": [item.to_dict() for item in questions], "readiness": report.to_dict()}

    def questions(self, store_id: str, unresolved_only: bool = True) -> list[dict[str, Any]]:
        questions = self.storage.list_records(store_id, "setup_question")
        if unresolved_only:
            return [item for item in questions if not item.get("resolved")]
        return questions

    def answer(self, store_id: str, question_id: str, answer: Any, actor: str) -> dict[str, Any]:
        record = self.storage.get_record(question_id)
        if not record or record.get("store_id") != store_id:
            raise KeyError(f"Unknown setup question: {question_id}")
        record["answer"] = answer
        record["resolved"] = True
        self.storage.put_record("setup_question", record)

        canonical = record["key"].split(":", 1)[1]
        profile = self.storage.get_setting(store_id, "profile", {})
        mappings = profile.get("mappings", [])
        mapping = next((item for item in mappings if item["canonical_field"] == canonical), None)
        if record["key"].startswith("verify:") and mapping:
            if answer is True or answer == mapping["source_path"] or answer == "yes":
                mapping["verified"] = True
            elif isinstance(answer, str) and "." in answer and answer != "none_of_these":
                old_path = mapping["source_path"]
                mapping["source_path"] = answer
                mapping["confidence"] = 1.0
                mapping["verified"] = True
                mapping["reasoning"] = (
                    f"Human corrected proposed mapping `{old_path}` during onboarding; confirmed by {actor}."
                )
            else:
                record["resolved"] = False
                self.storage.put_record("setup_question", record)
                raise ValueError("Rejected mapping remains unresolved; answer with the correct source path.")
        elif record["key"].startswith("map:"):
            if not isinstance(answer, str) or "." not in answer:
                record["resolved"] = False
                self.storage.put_record("setup_question", record)
                raise ValueError("A mapping answer must be a source path such as source.table.column.")
            mappings.append(
                Mapping(canonical, answer, 1.0, f"Confirmed by {actor} during onboarding.", True).to_dict()
            )

        profile["mappings"] = mappings
        self.storage.set_setting(store_id, "profile", profile)
        self.storage.add_audit(store_id, "setup_answered", actor, question_id, {"key": record["key"]})
        memory = StoreMemory(self.memory_root, store_id)
        memory.write_store_profile(profile)
        report = self.readiness(store_id)
        memory.write_readiness(report)
        return {"question": record, "readiness": report.to_dict()}

    def readiness(self, store_id: str) -> ReadinessReport:
        profile = self.storage.get_setting(store_id, "profile", {})
        mappings = {item["canonical_field"]: item for item in profile.get("mappings", [])}
        unresolved = len(self.questions(store_id, unresolved_only=True))

        groups = [
            ("purchase_mapping", "Purchase and product mapping", ("product.identity", "purchase.quantity")),
            ("pack_conversion", "Carton/pack/piece conversion", ("product.pack_size",)),
            ("locations", "Godown and shelf destinations", ("movement.destination",)),
            ("camera", "Camera source and zone purpose", ("camera.zone",)),
            ("routing", "DEO and staff role routing", ("staff.role",)),
        ]
        checks: list[ReadinessCheck] = []
        for key, label, fields in groups:
            missing = [field for field in fields if not mappings.get(field, {}).get("verified")]
            checks.append(
                ReadinessCheck(
                    key=key,
                    label=label,
                    passed=not missing,
                    detail="Verified" if not missing else f"Awaiting: {', '.join(missing)}",
                )
            )
        return ReadinessReport(
            store_id=store_id,
            checks=checks,
            unresolved_questions=unresolved,
            authority=[AuthorityLevel.OBSERVE, AuthorityLevel.LOCAL_WORK, AuthorityLevel.EXTERNAL_REVERSIBLE],
        )
