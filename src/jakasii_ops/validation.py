from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .connectors import SqlServerConnector, SqlServerConnectorError, _quote_identifier


NUMERIC_TYPES = {
    "bigint",
    "decimal",
    "float",
    "int",
    "money",
    "numeric",
    "real",
    "smallint",
    "smallmoney",
    "tinyint",
}


@dataclass(slots=True)
class SqlServerMappingValidator:
    """Validate proposed meanings with aggregate shape checks, never row values."""

    server: str
    database: str
    store_id: str
    store_name: str
    schema_catalog: dict[str, Any]
    awareness: dict[str, Any]
    profile: dict[str, Any]

    def _source(self) -> dict[str, Any]:
        sources = [
            source
            for source in self.schema_catalog.get("sources", [])
            if source.get("kind") == "sqlserver"
        ]
        exact = [
            source
            for source in sources
            if str(source.get("server", "")).lower() == self.server.lower()
            and str(source.get("database", "")).lower() == self.database.lower()
        ]
        selected = exact or sources
        if not selected:
            raise SqlServerConnectorError("No SQL Server source exists in the schema catalog.")
        return selected[0]

    @staticmethod
    def _quote_table(table: dict[str, Any]) -> str:
        parts = str(table.get("name", "")).split(".")
        if len(parts) != 2:
            raise ValueError("SQL Server catalog tables must be schema.table paths.")
        return ".".join(_quote_identifier(part) for part in parts)

    def _mapping_target(
        self, canonical: str, source: dict[str, Any]
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], str] | None:
        mapping = next(
            (
                item
                for item in self.profile.get("mappings", [])
                if item.get("canonical_field") == canonical
            ),
            None,
        )
        if not mapping or mapping.get("verified"):
            return None
        for table in source.get("tables", []):
            table_path = f"{source['name']}.{table['name']}"
            prefix = f"{table_path}."
            path = str(mapping.get("source_path", ""))
            if not path.startswith(prefix):
                continue
            column_name = path[len(prefix) :]
            column = next(
                (
                    item
                    for item in table.get("columns", [])
                    if item.get("name") == column_name
                ),
                None,
            )
            if column:
                return mapping, table, column, table_path
        return None

    def _role_confidence(self, role: str, table_path: str) -> float:
        return max(
            (
                float(item.get("confidence", 0.0))
                for item in self.awareness.get("role_candidates", {}).get(role, [])
                if item.get("source_path") == table_path
            ),
            default=0.0,
        )

    @staticmethod
    def _ratio(numerator: int, denominator: int) -> float:
        return round(numerator / denominator, 4) if denominator else 0.0

    def _runner(self) -> SqlServerConnector:
        return SqlServerConnector(
            self.server, self.database, self.store_id, self.store_name
        )

    def _identity_report(
        self,
        mapping: dict[str, Any],
        table: dict[str, Any],
        column: dict[str, Any],
        table_path: str,
    ) -> dict[str, Any]:
        quoted = _quote_identifier(str(column["name"]))
        rows = self._runner()._run_json(
            f"SELECT COUNT_BIG(*) AS row_count, COUNT({quoted}) AS nonnull_count, "
            f"COUNT(DISTINCT {quoted}) AS distinct_count "
            f"FROM {self._quote_table(table)} FOR JSON PATH;"
        )[0]
        row_count = int(rows.get("row_count", 0))
        nonnull = int(rows.get("nonnull_count", 0))
        distinct = int(rows.get("distinct_count", 0))
        nonnull_ratio = self._ratio(nonnull, row_count)
        uniqueness_ratio = self._ratio(distinct, nonnull)
        role_confidence = self._role_confidence("product_catalog", table_path)
        passed = (
            row_count >= 10
            and nonnull_ratio >= 0.98
            and uniqueness_ratio >= 0.98
            and role_confidence >= 0.90
            and float(mapping.get("confidence", 0.0)) >= 0.95
        )
        return {
            "canonical_field": "product.identity",
            "source_path": mapping["source_path"],
            "passed": passed,
            "confidence": 0.99 if passed else float(mapping.get("confidence", 0.0)),
            "basis": "aggregate_identity_shape",
            "metrics": {
                "row_count": row_count,
                "nonnull_ratio": nonnull_ratio,
                "uniqueness_ratio": uniqueness_ratio,
                "role_confidence": role_confidence,
            },
        }

    def _numeric_report(
        self,
        canonical: str,
        role: str,
        mapping: dict[str, Any],
        table: dict[str, Any],
        column: dict[str, Any],
        table_path: str,
    ) -> dict[str, Any]:
        data_type = str(column.get("type", "")).lower()
        if data_type not in NUMERIC_TYPES:
            return {
                "canonical_field": canonical,
                "source_path": mapping["source_path"],
                "passed": False,
                "confidence": float(mapping.get("confidence", 0.0)),
                "basis": "aggregate_numeric_shape",
                "metrics": {"numeric_type": False},
            }
        quoted = _quote_identifier(str(column["name"]))
        rows = self._runner()._run_json(
            f"SELECT COUNT_BIG(*) AS row_count, COUNT({quoted}) AS nonnull_count, "
            f"SUM(CASE WHEN {quoted} > 0 THEN 1 ELSE 0 END) AS positive_count, "
            f"SUM(CASE WHEN {quoted} < 0 THEN 1 ELSE 0 END) AS negative_count "
            f"FROM {self._quote_table(table)} FOR JSON PATH;"
        )[0]
        row_count = int(rows.get("row_count", 0))
        nonnull = int(rows.get("nonnull_count", 0))
        positive = int(rows.get("positive_count", 0) or 0)
        negative = int(rows.get("negative_count", 0) or 0)
        nonnull_ratio = self._ratio(nonnull, row_count)
        positive_ratio = self._ratio(positive, nonnull)
        negative_ratio = self._ratio(negative, nonnull)
        role_confidence = self._role_confidence(role, table_path)
        if canonical == "purchase.quantity":
            passed = (
                row_count >= 10
                and nonnull_ratio >= 0.98
                and positive_ratio >= 0.90
                and negative_ratio <= 0.01
                and role_confidence >= 0.90
                and float(mapping.get("confidence", 0.0)) >= 0.95
            )
        else:
            passed = (
                row_count >= 20
                and nonnull_ratio >= 0.50
                and positive_ratio >= 0.50
                and negative_ratio == 0.0
                and role_confidence >= 0.80
                and float(mapping.get("confidence", 0.0)) >= 0.95
            )
        return {
            "canonical_field": canonical,
            "source_path": mapping["source_path"],
            "passed": passed,
            "confidence": 0.99 if passed else float(mapping.get("confidence", 0.0)),
            "basis": "aggregate_numeric_shape",
            "metrics": {
                "row_count": row_count,
                "nonnull_ratio": nonnull_ratio,
                "positive_ratio": positive_ratio,
                "negative_ratio": negative_ratio,
                "role_confidence": role_confidence,
            },
        }

    def _destination_report(
        self,
        mapping: dict[str, Any],
        table: dict[str, Any],
        column: dict[str, Any],
        table_path: str,
    ) -> dict[str, Any]:
        quoted = _quote_identifier(str(column["name"]))
        rows = self._runner()._run_json(
            f"SELECT COUNT_BIG(*) AS row_count, COUNT({quoted}) AS nonnull_count, "
            f"COUNT(DISTINCT {quoted}) AS distinct_count "
            f"FROM {self._quote_table(table)} FOR JSON PATH;"
        )[0]
        row_count = int(rows.get("row_count", 0))
        nonnull = int(rows.get("nonnull_count", 0))
        distinct = int(rows.get("distinct_count", 0))
        nonnull_ratio = self._ratio(nonnull, row_count)
        role_confidence = self._role_confidence("stock_movement", table_path)
        passed = (
            row_count >= 10
            and nonnull_ratio >= 0.90
            and distinct >= 2
            and role_confidence >= 0.90
            and float(mapping.get("confidence", 0.0)) >= 0.95
        )
        return {
            "canonical_field": "movement.destination",
            "source_path": mapping["source_path"],
            "passed": passed,
            "confidence": 0.99 if passed else float(mapping.get("confidence", 0.0)),
            "basis": "aggregate_destination_shape",
            "metrics": {
                "row_count": row_count,
                "nonnull_ratio": nonnull_ratio,
                "distinct_count": distinct,
                "role_confidence": role_confidence,
            },
        }

    def validate(self) -> list[dict[str, Any]]:
        source = self._source()
        reports: list[dict[str, Any]] = []
        checks = (
            ("product.identity", "product_catalog"),
            ("purchase.quantity", "purchase_line"),
            ("product.pack_size", "product_catalog"),
            ("movement.destination", "stock_movement"),
        )
        for canonical, role in checks:
            target = self._mapping_target(canonical, source)
            if not target:
                continue
            mapping, table, column, table_path = target
            try:
                if canonical == "product.identity":
                    report = self._identity_report(mapping, table, column, table_path)
                elif canonical in {"purchase.quantity", "product.pack_size"}:
                    report = self._numeric_report(
                        canonical, role, mapping, table, column, table_path
                    )
                else:
                    report = self._destination_report(
                        mapping, table, column, table_path
                    )
            except Exception as exc:
                report = {
                    "canonical_field": canonical,
                    "source_path": mapping["source_path"],
                    "passed": False,
                    "confidence": float(mapping.get("confidence", 0.0)),
                    "basis": "aggregate_validation_failed",
                    "metrics": {"error": type(exc).__name__},
                }
            reports.append(report)
        return reports
