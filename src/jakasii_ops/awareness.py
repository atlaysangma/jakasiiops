from __future__ import annotations

import re
from itertools import combinations
from typing import Any

from .models import utc_now


def normalize(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.lower())


ROLE_RULES: dict[str, dict[str, Any]] = {
    "product_catalog": {
        "table": ("product", "item", "sku", "catalog"),
        "groups": (("itemid", "productid", "itemcode", "productcode", "sku"),
                   ("itemname", "productname", "description", "name")),
        "positive": ("master", "mas", "mst", "catalog"),
    },
    "sale_header": {
        "table": ("sale", "invoice", "bill", "checkout", "pos"),
        "groups": (("saledate", "invoicedate", "billdate", "date"),
                   ("netamt", "total", "grossamt", "amount")),
        "positive": ("header", "hdr"),
        "negative": ("detail", "dtl", "line"),
    },
    "sale_line": {
        "table": ("sale", "invoice", "bill", "checkout", "pos"),
        "groups": (("qty", "quantity", "soldqty"),
                   ("itemid", "productid", "itemcode", "sku")),
        "positive": ("detail", "dtl", "line"),
    },
    "purchase_header": {
        "table": ("purchase", "receipt", "receiving", "inward", "goodsreceived"),
        "groups": (("purchasedate", "receiptdate", "receiveddate", "date"),
                   ("netamt", "total", "grossamt", "amount")),
        "positive": ("header", "hdr"),
        "negative": ("detail", "dtl", "line"),
    },
    "purchase_line": {
        "table": ("purchase", "receipt", "receiving", "inward", "goodsreceived"),
        "groups": (("qty", "quantity", "receivedqty"),
                   ("itemid", "productid", "itemcode", "sku")),
        "positive": ("detail", "dtl", "line"),
    },
    "inventory_stock": {
        "table": ("stock", "inventory", "onhand"),
        "groups": (("qty", "quantity", "onhand", "balance"),
                   ("itemid", "productid", "itemcode", "sku")),
        "positive": ("stock", "inventory"),
    },
    "stock_movement": {
        "table": ("movement", "transfer", "issue", "dispatch", "godown", "warehouse", "shelf"),
        "groups": (("qty", "quantity", "units"),
                   ("destination", "source", "location", "godown", "warehouse", "shelf")),
        "positive": ("movement", "transfer", "issue", "dispatch"),
    },
    "damage_expiry": {
        "table": ("damage", "expiry", "expired", "waste", "stock", "inventory"),
        "groups": (("damageqty", "expiryqty", "wastage", "brokenqty", "expdate"),),
        "positive": ("damage", "expiry", "waste"),
    },
    "staff_directory": {
        "table": ("staff", "employee", "worker", "user", "emp"),
        "groups": (("staffid", "employeeid", "userid", "empid", "uid"),
                   ("role", "designation", "duty", "jobtitle")),
        "positive": ("staff", "employee", "worker", "emp"),
    },
    "attendance": {
        "table": ("attendance", "shift", "punch", "timesheet"),
        "groups": (("staffid", "employeeid", "userid", "empid", "uid"),
                   ("inat", "outat", "checkin", "checkout", "status", "shift")),
        "positive": ("attendance", "punch", "timesheet"),
    },
    "camera_registry": {
        "table": ("camera", "cctv", "channel", "stream"),
        "groups": (("channel", "cameraid", "streamid"),
                   ("role", "zone", "location", "name")),
        "positive": ("camera", "cctv", "channel"),
    },
    "camera_events": {
        "table": ("camera", "event", "observation", "detection"),
        "groups": (("eventid", "observationid", "detectionid"),
                   ("startedat", "endedat", "occurredat", "timestamp"),
                   ("channel", "cameraid", "streamid")),
        "positive": ("event", "observation", "detection"),
    },
}


class StoreAwarenessEngine:
    """Build an unverified operational model from structural metadata only."""

    @staticmethod
    def _contains(values: set[str], tokens: tuple[str, ...]) -> bool:
        return any(token in value for value in values for token in tokens)

    def _score(self, table: dict[str, Any], rule: dict[str, Any]) -> tuple[float, list[str]]:
        table_name = normalize(str(table.get("name", "")))
        columns = {normalize(str(column.get("name", ""))) for column in table.get("columns", [])}
        evidence: list[str] = []
        score = 0.0
        if any(token in table_name for token in rule["table"]):
            score += 0.38
            evidence.append("table name matches the operational vocabulary")
        matched_groups = 0
        for group in rule.get("groups", ()):
            if self._contains(columns, group):
                matched_groups += 1
        if rule.get("groups"):
            score += 0.44 * (matched_groups / len(rule["groups"]))
            if matched_groups:
                evidence.append(
                    f"{matched_groups}/{len(rule['groups'])} expected column signatures matched"
                )
        if any(token in table_name for token in rule.get("positive", ())):
            score += 0.14
            evidence.append("table shape modifier supports this role")
        if any(token in table_name for token in rule.get("negative", ())):
            score -= 0.22
            evidence.append("table shape modifier conflicts with this role")
        if (
            table_name.startswith("sys")
            or any(token in table_name for token in ("report", "rpt", "temp", "config", "setting", "form"))
        ):
            score -= 0.28
            evidence.append("report/configuration shape reduces operational confidence")
        return round(max(0.0, min(score, 0.96)), 2), evidence

    @staticmethod
    def _table_path(source: dict[str, Any], table: dict[str, Any]) -> str:
        return f"{source['name']}.{table['name']}"

    def build(self, document: dict[str, Any]) -> dict[str, Any]:
        table_index: dict[str, dict[str, Any]] = {}
        role_candidates: dict[str, list[dict[str, Any]]] = {}
        for source in document.get("sources", []):
            for table in source.get("tables", []):
                path = self._table_path(source, table)
                table_index[path] = table
                for role, rule in ROLE_RULES.items():
                    confidence, evidence = self._score(table, rule)
                    if confidence < 0.50:
                        continue
                    role_candidates.setdefault(role, []).append(
                        {
                            "role": role,
                            "source_path": path,
                            "confidence": confidence,
                            "verified": False,
                            "evidence": evidence,
                            "row_count": table.get("row_count"),
                        }
                    )
        for candidates in role_candidates.values():
            candidates.sort(key=lambda item: (item["confidence"], item.get("row_count") or 0), reverse=True)
            del candidates[5:]

        declared_relationships: list[dict[str, Any]] = []
        for source in document.get("sources", []):
            for relation in source.get("relationships", []):
                declared_relationships.append(
                    relation
                    | {
                        "from_table": f"{source['name']}.{relation['from_table']}",
                        "to_table": f"{source['name']}.{relation['to_table']}",
                    }
                )

        candidate_paths = {
            item["source_path"]
            for candidates in role_candidates.values()
            for item in candidates[:2]
        }
        inferred_relationships: list[dict[str, Any]] = []
        for left_path, right_path in combinations(sorted(candidate_paths), 2):
            left = table_index[left_path]
            right = table_index[right_path]
            left_columns = {
                normalize(str(column.get("name", ""))): column for column in left.get("columns", [])
            }
            right_columns = {
                normalize(str(column.get("name", ""))): column for column in right.get("columns", [])
            }
            shared = [
                name
                for name in left_columns.keys() & right_columns.keys()
                if len(name) >= 5 and (name.endswith("id") or name.endswith("code"))
            ]
            if not shared:
                continue
            shared.sort(
                key=lambda name: bool(left_columns[name].get("primary_key"))
                or bool(right_columns[name].get("primary_key")),
                reverse=True,
            )
            column = shared[0]
            has_key = bool(left_columns[column].get("primary_key")) or bool(
                right_columns[column].get("primary_key")
            )
            inferred_relationships.append(
                {
                    "kind": "inferred_shared_identifier",
                    "from_table": left_path,
                    "from_column": left_columns[column].get("name"),
                    "to_table": right_path,
                    "to_column": right_columns[column].get("name"),
                    "confidence": 0.82 if has_key else 0.64,
                    "verified": False,
                    "reason": "Shared identifier column; requires validation before use.",
                }
            )
            if len(inferred_relationships) >= 100:
                break

        capability_thresholds = {
            "staff_directory": 0.80,
            "attendance": 0.80,
        }
        capabilities = sorted(
            role
            for role, candidates in role_candidates.items()
            if candidates
            and candidates[0]["confidence"] >= capability_thresholds.get(role, 0.60)
        )
        contracted_capabilities = {
            "staff_directory"
            for source in document.get("sources", [])
            for contract in source.get("semantic_contracts", [])
            if contract.get("canonical_field") == "staff.role"
            and contract.get("authority") == "authorized_connector_contract"
        }
        capabilities = sorted(set(capabilities) | contracted_capabilities)
        required_roles = (
            "product_catalog",
            "purchase_header",
            "purchase_line",
            "sale_header",
            "sale_line",
            "inventory_stock",
            "camera_registry",
            "camera_events",
            "staff_directory",
        )
        unknowns = [role for role in required_roles if role not in capabilities]
        channel_catalogs = [
            channel
            for source in document.get("sources", [])
            for channel in source.get("entities", {}).get("camera_channels", [])
        ]
        return {
            "store_id": document["store_id"],
            "generated_at": utc_now(),
            "basis": "structural_metadata_only",
            "verified": False,
            "sources": [source.get("name") for source in document.get("sources", [])],
            "table_count": len(table_index),
            "column_count": sum(
                len(table.get("columns", [])) for table in table_index.values()
            ),
            "role_candidates": role_candidates,
            "capabilities_observed": capabilities,
            "unknowns": unknowns,
            "declared_relationships": declared_relationships,
            "inferred_relationships": inferred_relationships,
            "camera_channels": channel_catalogs,
            "camera_channel_count": len(channel_catalogs),
            "next_safe_step": "Confirm high-impact role and join candidates before reading business rows.",
        }
