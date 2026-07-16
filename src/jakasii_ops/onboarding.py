from __future__ import annotations

import json
import re
from dataclasses import asdict
from pathlib import Path
from typing import Any

from .awareness import StoreAwarenessEngine
from .connectors import SchemaConnector
from .memory import StoreMemory
from .models import (
    AuthorityLevel,
    Mapping,
    ReadinessCheck,
    ReadinessReport,
    SetupQuestion,
    utc_now,
)
from .reasoning import DeterministicReasoner, ReasoningProvider
from .storage import OpsStore


CANONICAL_FIELDS: dict[str, dict[str, Any]] = {
    "product.identity": {
        "tokens": ("productid", "productcode", "itemcode", "sku", "pcode", "prodid"),
        "table_tokens": ("product", "item", "sku", "catalog"),
        "required": True,
        "label": "Product/SKU identity",
    },
    "purchase.quantity": {
        "tokens": ("quantity", "qty", "pieces", "pcs", "purchaseqty", "receivedqty"),
        "table_tokens": ("purchase", "receipt", "receiving", "inward", "goodsreceived"),
        "required": True,
        "label": "Purchase/receiving quantity",
    },
    "product.pack_size": {
        "tokens": ("packsize", "unitspercase", "pcspercarton", "conversion", "packing", "factor"),
        "column_groups": (
            ("carton", "cartoon", "case", "box"),
            ("pcs", "piece", "unit"),
        ),
        "table_tokens": ("product", "item", "stock", "purchase", "catalog"),
        "required": True,
        "label": "Carton/pack/piece conversion",
    },
    "movement.destination": {
        "tokens": ("destination", "destinationid", "dest", "godown", "warehouse", "location", "locationid"),
        "weak_tokens": ("location", "locationid"),
        "table_tokens": ("movement", "transfer", "stock", "godown", "warehouse", "shelf", "receipt"),
        "required": True,
        "label": "Godown/shelf destination",
    },
    "camera.zone": {
        "tokens": (
            "camerazone",
            "cameraname",
            "cameraid",
            "channel",
            "camchannel",
            "zone",
            "zonename",
            "area",
            "role",
            "streamid",
        ),
        "table_tokens": ("camera", "cctv", "channel", "stream", "zone"),
        "weak_tokens": ("channel", "cameraid", "streamid"),
        "required": True,
        "label": "Camera channel and monitored zone",
    },
    "staff.role": {
        "tokens": ("staffrole", "role", "designation", "duty", "jobtitle"),
        "table_tokens": ("staff", "employee", "worker", "user", "role", "emp"),
        "required": True,
        "label": "DEO/staff task routing",
    },
    "sale.quantity": {
        "tokens": ("saleqty", "soldqty", "unitsold", "billqty"),
        "table_tokens": ("sale", "bill", "invoice", "pos"),
        "required": False,
        "label": "POS sale quantity",
    },
    "damage.quantity": {
        "tokens": ("damageqty", "damagedunits", "wastage", "brokenqty"),
        "table_tokens": ("damage", "stock", "item", "product"),
        "required": False,
        "label": "Damage quantity",
    },
    "attendance.identity": {
        "tokens": ("badgeid", "staffid", "employeeid", "attendanceid"),
        "table_tokens": ("attendance", "staff", "employee", "worker", "emp"),
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
                            "normalized_table": normalize_name(table["name"]),
                            "type": column.get("type", "unknown"),
                            "samples": column.get("samples", [])[:5],
                        }
                    )
        return columns


class MappingEngine:
    def __init__(self, reasoner: ReasoningProvider | None = None) -> None:
        self.reasoner = reasoner or DeterministicReasoner()

    @staticmethod
    def _score(column: dict[str, Any], config: dict[str, Any]) -> float:
        name = column["normalized"]
        tokens = config["tokens"]
        table_name = column.get("normalized_table", "")
        table_match = any(
            len(token) >= 3 and token in table_name for token in config.get("table_tokens", ())
        )
        if name in {"id", "name", "role", "unit", "qty", "quantity"} and not table_match:
            return 0.0
        weak_tokens = config.get("weak_tokens", ())
        if name in tokens:
            column_score = 0.62 if name in weak_tokens else 0.78
        elif any(len(token) >= 3 and token in name for token in tokens):
            column_score = 0.58 if any(token in name for token in weak_tokens) else 0.66
        elif config.get("column_groups") and all(
            any(token in name for token in group) for group in config["column_groups"]
        ):
            column_score = 0.76
        else:
            return 0.0
        score = column_score + (0.20 if table_match else 0.0)
        if config.get("label") == "Godown/shelf destination":
            if name.endswith(("to", "dest", "destination")):
                score += 0.16
            if name.endswith(("from", "form", "source")):
                score -= 0.30
        if (
            table_name.startswith("sys")
            or any(token in table_name for token in ("report", "rpt", "temp", "config", "setting", "form"))
        ):
            score -= 0.28
        return max(0.0, min(score, 0.98))

    def candidates(
        self, document: dict[str, Any], canonical: str, limit: int = 5
    ) -> list[str]:
        config = CANONICAL_FIELDS[canonical]
        columns = SchemaDiscovery().flatten_columns(document)
        ranked = sorted(
            ((self._score(column, config), column["path"]) for column in columns),
            key=lambda item: item[0],
            reverse=True,
        )
        return [path for score, path in ranked if score > 0][:limit]

    def propose(self, document: dict[str, Any]) -> list[Mapping]:
        columns = SchemaDiscovery().flatten_columns(document)
        mappings: list[Mapping] = []
        for canonical, config in CANONICAL_FIELDS.items():
            ranked = sorted(
                ((self._score(column, config), column) for column in columns),
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
            requires_confirmation = bool(document.get("requires_mapping_confirmation"))
            mappings.append(
                Mapping(
                    canonical_field=canonical,
                    source_path=best["path"],
                    confidence=round(best_score, 2),
                    reasoning=reasoning,
                    verified=best_score >= 0.95 and not requires_confirmation,
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
        return self._start_document(document)

    def start_connector(self, connector: SchemaConnector) -> dict[str, Any]:
        """Discover and onboard directly from a read-only live connector."""

        document = connector.inspect_schema()
        required = {"store_id", "name", "sources"}
        missing = required - set(document)
        if missing:
            raise ValueError(f"Connector schema is missing: {', '.join(sorted(missing))}")
        if not document.get("sources"):
            raise ValueError("Connector discovered no schema sources.")
        return self._start_document(document)

    def _start_document(self, document: dict[str, Any]) -> dict[str, Any]:
        store_id = document["store_id"]
        mappings = self.mapper.propose(document)
        semantic_contracts = {
            contract["canonical_field"]: {
                "source_path": f"{source['name']}.{contract['table']}.{contract['column']}",
                "authority": contract.get("authority"),
            }
            for source in document.get("sources", [])
            for contract in source.get("semantic_contracts", [])
            if contract.get("canonical_field")
            and contract.get("table")
            and contract.get("column")
            and contract.get("authority") == "authorized_connector_contract"
        }
        for mapping in mappings:
            contract = semantic_contracts.get(mapping.canonical_field)
            if not contract or mapping.source_path != contract["source_path"]:
                continue
            mapping.verified = True
            mapping.confidence = 1.0
            mapping.reasoning = (
                "Verified by an authorized connector semantic contract, not lexical inference."
            )
        available_paths = {
            column["path"] for column in self.discovery.flatten_columns(document)
        }
        previous_profile = self.storage.get_setting(store_id, "profile", {})
        for previous in previous_profile.get("mappings", []):
            if not previous.get("verified") or previous.get("source_path") not in available_paths:
                continue
            current = next(
                (
                    mapping
                    for mapping in mappings
                    if mapping.canonical_field == previous.get("canonical_field")
                ),
                None,
            )
            restored = Mapping(
                canonical_field=previous["canonical_field"],
                source_path=previous["source_path"],
                confidence=1.0,
                reasoning="Previously confirmed mapping remains present after schema rescan.",
                verified=True,
            )
            if current:
                mappings[mappings.index(current)] = restored
            else:
                mappings.append(restored)
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
                    # Live connectors deliberately provide alternatives because
                    # a lexical match is a hypothesis, never a verified fact.
                    SetupQuestion(
                        store_id=store_id,
                        key=f"verify:{canonical}",
                        prompt=f"Does `{mapping.source_path}` represent {config['label'].lower()}?",
                        reason=f"Proposed at confidence {mapping.confidence:.2f}; important meanings require confirmation.",
                        options=list(
                            dict.fromkeys(
                                self.mapper.candidates(document, canonical)
                                + [mapping.source_path, "none_of_these"]
                            )
                        ),
                    )
                )

        profile = {
            "store_id": store_id,
            "name": document["name"],
            "sources": [source["name"] for source in document["sources"]],
            "schema_file": document.get("schema_file"),
            "schema_source": document.get("schema_source"),
            "requires_mapping_confirmation": bool(
                document.get("requires_mapping_confirmation")
            ),
            "discovered_tables": sum(
                len(source.get("tables", [])) for source in document["sources"]
            ),
            "discovered_columns": sum(
                len(table.get("columns", []))
                for source in document["sources"]
                for table in source.get("tables", [])
            ),
            "discovered_relationships": sum(
                len(source.get("relationships", [])) for source in document["sources"]
            ),
            "discovered_camera_channels": sum(
                len(source.get("entities", {}).get("camera_channels", []))
                for source in document["sources"]
            ),
            "mappings": [mapping.to_dict() for mapping in mappings],
            "discovered_fields": sorted(mapped_fields),
        }
        schema_catalog = {
            "store_id": store_id,
            "captured_at": utc_now(),
            "schema_source": document.get("schema_source"),
            "sources": [],
        }
        for source in document["sources"]:
            catalog_source = {
                key: source[key]
                for key in ("name", "kind", "server", "database", "path", "access", "device")
                if key in source
            }
            if source.get("semantic_contracts"):
                catalog_source["semantic_contracts"] = [
                    {
                        key: contract.get(key)
                        for key in ("canonical_field", "table", "column", "authority")
                        if contract.get(key) is not None
                    }
                    for contract in source.get("semantic_contracts", [])
                ]
            catalog_source["tables"] = []
            for table in source.get("tables", []):
                catalog_source["tables"].append(
                    {
                        key: value
                        for key, value in {
                            "schema": table.get("schema"),
                            "name": table.get("name"),
                            "row_count": table.get("row_count"),
                            "columns": [
                                {
                                    field: column.get(field)
                                    for field in (
                                        "name",
                                        "type",
                                        "nullable",
                                        "primary_key",
                                        "max_length",
                                        "precision",
                                        "scale",
                                    )
                                    if field in column
                                }
                                for column in table.get("columns", [])
                            ],
                        }.items()
                        if value is not None
                    }
                )
            catalog_source["relationships"] = [
                {
                    key: relationship.get(key)
                    for key in (
                        "kind",
                        "constraint",
                        "from_table",
                        "from_column",
                        "to_table",
                        "to_column",
                        "confidence",
                    )
                    if relationship.get(key) is not None
                }
                for relationship in source.get("relationships", [])
            ]
            camera_channels = source.get("entities", {}).get("camera_channels", [])
            staff_roles = source.get("entities", {}).get("staff_roles", [])
            if camera_channels or staff_roles:
                catalog_source["entities"] = {}
            if camera_channels:
                catalog_source["entities"]["camera_channels"] = [
                    {
                        key: channel.get(key)
                        for key in ("channel", "name", "role", "enabled", "entry_counter")
                        if key in channel
                    }
                    for channel in camera_channels
                ]
            if staff_roles:
                catalog_source["entities"]["staff_roles"] = [
                    {
                        "role": item.get("role"),
                        "count": item.get("count"),
                    }
                    for item in staff_roles
                ]
            schema_catalog["sources"].append(catalog_source)
        awareness = StoreAwarenessEngine().build(document)
        self.storage.set_setting(store_id, "profile", profile)
        self.storage.set_setting(store_id, "schema_catalog", schema_catalog)
        self.storage.set_setting(store_id, "awareness", awareness)
        self.storage.delete_records(store_id, "setup_question")
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
        memory.write_json_artifact("Schema-Catalog", schema_catalog)
        memory.write_json_artifact("Store-Awareness", awareness)
        memory.write_awareness(awareness)
        report = self.readiness(store_id)
        memory.write_readiness(report)
        return {"profile": profile, "questions": [item.to_dict() for item in questions], "readiness": report.to_dict()}

    def questions(self, store_id: str, unresolved_only: bool = True) -> list[dict[str, Any]]:
        questions = self.storage.list_records(store_id, "setup_question")
        if unresolved_only:
            return [item for item in questions if not item.get("resolved")]
        return questions

    def apply_validations(
        self, store_id: str, reports: list[dict[str, Any]]
    ) -> dict[str, Any]:
        """Promote mappings proven by privacy-safe aggregate database checks."""

        profile = self.storage.get_setting(store_id, "profile", {})
        mappings = profile.get("mappings", [])
        promoted: list[str] = []
        for validation in reports:
            if not validation.get("passed"):
                continue
            canonical = str(validation.get("canonical_field", ""))
            source_path = str(validation.get("source_path", ""))
            mapping = next(
                (
                    item
                    for item in mappings
                    if item.get("canonical_field") == canonical
                    and item.get("source_path") == source_path
                ),
                None,
            )
            if not mapping:
                continue
            mapping["verified"] = True
            mapping["confidence"] = max(
                float(mapping.get("confidence", 0.0)),
                float(validation.get("confidence", 0.0)),
            )
            mapping["reasoning"] = (
                "Verified autonomously from aggregate SQL shape checks; no business row "
                "values or personal fields were read into JAKASII memory."
            )
            mapping["verification_basis"] = validation.get("basis")
            promoted.append(canonical)

            for question in self.storage.list_records(store_id, "setup_question"):
                if question.get("key") != f"verify:{canonical}":
                    continue
                question["answer"] = source_path
                question["resolved"] = True
                question["resolved_by"] = "autonomous_aggregate_validator"
                self.storage.put_record("setup_question", question)

            self.storage.add_audit(
                store_id,
                "mapping_autonomously_validated",
                "jakasii",
                canonical,
                {
                    "source_path": source_path,
                    "basis": validation.get("basis"),
                },
            )

        profile["mappings"] = mappings
        self.storage.set_setting(store_id, "profile", profile)
        self.storage.set_setting(
            store_id,
            "mapping_validation",
            {"validated_at": utc_now(), "reports": reports, "promoted": promoted},
        )
        memory = StoreMemory(self.memory_root, store_id)
        memory.write_store_profile(profile)
        memory.write_json_artifact(
            "Mapping-Validation",
            {"validated_at": utc_now(), "reports": reports, "promoted": promoted},
        )
        readiness = self.readiness(store_id)
        memory.write_readiness(readiness)
        return {
            "reports": reports,
            "promoted": promoted,
            "readiness": readiness.to_dict(),
        }

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
