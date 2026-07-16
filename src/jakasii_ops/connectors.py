from __future__ import annotations

import json
import hashlib
import re
import shutil
import socket
import sqlite3
import subprocess
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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


@dataclass(slots=True)
class CameraRuntimeInspector:
    """Read a collector heartbeat without copying errors, secrets, or paths."""

    root: str | Path
    stale_seconds: int = 180

    @staticmethod
    def _parse_time(value: Any) -> datetime | None:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=datetime.now().astimezone().tzinfo)
        return parsed.astimezone(timezone.utc)

    def inspect(self) -> dict[str, Any]:
        root = Path(self.root).resolve()
        now = datetime.now(timezone.utc)
        health_files = list(root.glob("collector_health.json")) + list(
            root.glob("*/*collector_health.json")
        )
        health: dict[str, Any] = {}
        if health_files:
            try:
                document = json.loads(health_files[0].read_text(encoding="utf-8-sig"))
                if isinstance(document, dict):
                    health = document
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                health = {}

        updated = self._parse_time(health.get("updated_at"))
        heartbeat_age = round((now - updated).total_seconds(), 1) if updated else None
        database_files = list(root.glob("*.sqlite3")) + list(root.glob("*/*.sqlite3"))
        latest_database_mtime = max(
            (path.stat().st_mtime for path in database_files if path.is_file()),
            default=None,
        )
        event_store_age = (
            round(now.timestamp() - latest_database_mtime, 1)
            if latest_database_mtime is not None
            else None
        )
        status = str(health.get("status", "unknown")).lower()
        camera_status = str(health.get("camera_status", "unknown")).lower()
        if (
            heartbeat_age is not None
            and heartbeat_age <= self.stale_seconds
            and status == "running"
            and camera_status == "running"
        ):
            state = "running"
        elif heartbeat_age is not None and heartbeat_age > self.stale_seconds:
            state = "stale_heartbeat"
        elif health and status in {"stopped", "error"}:
            state = "not_running"
        elif event_store_age is not None and event_store_age > self.stale_seconds:
            state = "stale_event_store"
        else:
            state = "unmonitored"
        return {
            "state": state,
            "collector_status": status,
            "camera_status": camera_status,
            "sql_status": str(health.get("sql_status", "unknown")).lower(),
            "heartbeat_age_seconds": heartbeat_age,
            "event_store_age_seconds": event_store_age,
            "live_camera_ready": state == "running",
            "raw_error_persisted": False,
        }


class TaskSink(Protocol):
    """Existing staff/boss apps consume verification work through this boundary."""

    name: str

    def deliver(self, task: dict[str, Any]) -> str: ...


class ActionExecutor(Protocol):
    """A future hand must receive an already approved action request."""

    name: str

    def execute(self, approved_action: dict[str, Any]) -> dict[str, Any]: ...


class SqlServerConnectorError(RuntimeError):
    """Raised when read-only SQL Server discovery cannot be completed."""


class FirestoreConnectorError(RuntimeError):
    """Raised when privacy-safe staff-role discovery cannot be completed."""


_SQL_IDENTIFIER = re.compile(r"^[A-Za-z_][A-Za-z0-9_@$#]*$")


def _quote_identifier(value: str) -> str:
    if not _SQL_IDENTIFIER.fullmatch(value):
        raise ValueError(f"Unsafe SQL identifier: {value!r}")
    return f"[{value}]"


@dataclass(slots=True)
class SqlServerConnector:
    """Read-only SQL Server discovery through the installed ``sqlcmd`` client.

    The connector deliberately exposes only fixed catalog queries and bounded
    table sampling. It cannot execute caller-supplied SQL or mutate the source
    database. Authentication uses the current Windows account, so credentials
    never enter configuration, logs, store memory, or command output.
    """

    server: str
    database: str
    store_id: str
    store_name: str
    timeout_seconds: int = 30

    @property
    def name(self) -> str:
        raw = f"sqlserver_{self.server}_{self.database}"
        return re.sub(r"[^A-Za-z0-9_-]+", "_", raw).strip("_")

    def _run_json(self, query: str) -> Any:
        executable = shutil.which("sqlcmd")
        if not executable:
            raise SqlServerConnectorError(
                "sqlcmd was not found. Install Microsoft SQL Server command-line tools."
            )
        command = [
            executable,
            "-S",
            self.server,
            "-d",
            self.database,
            "-E",
            "-b",
            "-r",
            "1",
            "-y",
            "0",
            "-Q",
            f"SET NOCOUNT ON; SET LOCK_TIMEOUT 3000; {query}",
        ]
        try:
            completed = subprocess.run(
                command,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self.timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise SqlServerConnectorError(
                f"SQL Server discovery timed out after {self.timeout_seconds} seconds."
            ) from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout).strip()
            raise SqlServerConnectorError(
                f"SQL Server discovery failed ({completed.returncode}): {detail}"
            )
        payload = completed.stdout.lstrip("\ufeff").strip()
        if not payload:
            return []
        # ``sqlcmd -y 0`` preserves arbitrarily long JSON but cannot be combined
        # with ``-h -1`` on older clients. Locate the first JSON value beneath
        # the generated column heading and let raw_decode ignore that prefix.
        starts = [position for token in ("[", "{") if (position := payload.find(token)) >= 0]
        if not starts:
            preview = payload[:200].replace("\n", " ")
            raise SqlServerConnectorError(f"sqlcmd returned no JSON value: {preview}")
        try:
            json_text = payload[min(starts) :].replace("\r", "").replace("\n", "")
            result, _end = json.JSONDecoder().raw_decode(json_text)
            return result
        except json.JSONDecodeError as exc:
            preview = payload[:200].replace("\n", " ")
            raise SqlServerConnectorError(
                f"sqlcmd returned invalid JSON: {preview}"
            ) from exc

    def inspect_schema(self) -> dict[str, Any]:
        rows = self._run_json(
            """
            SELECT
                schemas.name AS schema_name,
                tables.name AS table_name,
                columns.name AS column_name,
                types.name AS data_type,
                columns.max_length,
                columns.precision,
                columns.scale,
                columns.is_nullable,
                CONVERT(bit, CASE WHEN primary_keys.column_id IS NULL THEN 0 ELSE 1 END)
                    AS is_primary_key
            FROM sys.tables AS tables
            INNER JOIN sys.schemas AS schemas ON schemas.schema_id = tables.schema_id
            INNER JOIN sys.columns AS columns ON columns.object_id = tables.object_id
            INNER JOIN sys.types AS types ON types.user_type_id = columns.user_type_id
            LEFT JOIN (
                SELECT index_columns.object_id, index_columns.column_id
                FROM sys.indexes AS indexes
                INNER JOIN sys.index_columns AS index_columns
                    ON index_columns.object_id = indexes.object_id
                    AND index_columns.index_id = indexes.index_id
                WHERE indexes.is_primary_key = 1
            ) AS primary_keys
                ON primary_keys.object_id = columns.object_id
                AND primary_keys.column_id = columns.column_id
            WHERE tables.is_ms_shipped = 0
            ORDER BY schemas.name, tables.name, columns.column_id
            FOR JSON PATH;
            """
        )
        table_stats = self._run_json(
            """
            SELECT
                schemas.name AS schema_name,
                tables.name AS table_name,
                SUM(partitions.rows) AS row_count
            FROM sys.tables AS tables
            INNER JOIN sys.schemas AS schemas ON schemas.schema_id = tables.schema_id
            INNER JOIN sys.partitions AS partitions ON partitions.object_id = tables.object_id
            WHERE tables.is_ms_shipped = 0 AND partitions.index_id IN (0, 1)
            GROUP BY schemas.name, tables.name
            ORDER BY schemas.name, tables.name
            FOR JSON PATH;
            """
        )
        relationship_rows = self._run_json(
            """
            SELECT
                parent_schemas.name AS from_schema,
                parent_tables.name AS from_table,
                parent_columns.name AS from_column,
                referenced_schemas.name AS to_schema,
                referenced_tables.name AS to_table,
                referenced_columns.name AS to_column,
                foreign_keys.name AS constraint_name
            FROM sys.foreign_key_columns AS foreign_key_columns
            INNER JOIN sys.foreign_keys AS foreign_keys
                ON foreign_keys.object_id = foreign_key_columns.constraint_object_id
            INNER JOIN sys.tables AS parent_tables
                ON parent_tables.object_id = foreign_key_columns.parent_object_id
            INNER JOIN sys.schemas AS parent_schemas
                ON parent_schemas.schema_id = parent_tables.schema_id
            INNER JOIN sys.columns AS parent_columns
                ON parent_columns.object_id = foreign_key_columns.parent_object_id
                AND parent_columns.column_id = foreign_key_columns.parent_column_id
            INNER JOIN sys.tables AS referenced_tables
                ON referenced_tables.object_id = foreign_key_columns.referenced_object_id
            INNER JOIN sys.schemas AS referenced_schemas
                ON referenced_schemas.schema_id = referenced_tables.schema_id
            INNER JOIN sys.columns AS referenced_columns
                ON referenced_columns.object_id = foreign_key_columns.referenced_object_id
                AND referenced_columns.column_id = foreign_key_columns.referenced_column_id
            ORDER BY parent_schemas.name, parent_tables.name, foreign_keys.name,
                     foreign_key_columns.constraint_column_id
            FOR JSON PATH;
            """
        )
        row_counts = {
            (str(row["schema_name"]), str(row["table_name"])): int(row.get("row_count", 0))
            for row in table_stats
        }
        tables: dict[tuple[str, str], dict[str, Any]] = {}
        for row in rows:
            schema_name = str(row["schema_name"])
            table_name = str(row["table_name"])
            table = tables.setdefault(
                (schema_name, table_name),
                {
                    "schema": schema_name,
                    "name": f"{schema_name}.{table_name}",
                    "row_count": row_counts.get((schema_name, table_name), 0),
                    "columns": [],
                },
            )
            table["columns"].append(
                {
                    "name": str(row["column_name"]),
                    "type": str(row["data_type"]),
                    "nullable": bool(row.get("is_nullable", False)),
                    "primary_key": bool(row.get("is_primary_key", False)),
                    "max_length": row.get("max_length"),
                    "precision": row.get("precision"),
                    "scale": row.get("scale"),
                    "samples": [],
                }
            )
        return {
            "store_id": self.store_id,
            "name": self.store_name,
            "sources": [
                {
                    "name": self.name,
                    "kind": "sqlserver",
                    "server": self.server,
                    "database": self.database,
                    "access": "read_only_discovery",
                    "tables": list(tables.values()),
                    "relationships": [
                        {
                            "kind": "declared_foreign_key",
                            "constraint": row.get("constraint_name"),
                            "from_table": f"{row['from_schema']}.{row['from_table']}",
                            "from_column": row["from_column"],
                            "to_table": f"{row['to_schema']}.{row['to_table']}",
                            "to_column": row["to_column"],
                            "confidence": 1.0,
                        }
                        for row in relationship_rows
                    ],
                }
            ],
            "schema_source": {
                "connector": "sqlserver",
                "server": self.server,
                "database": self.database,
                "authentication": "windows",
            },
            "requires_mapping_confirmation": True,
        }

    def sample_records(self, table: str, limit: int = 5) -> list[dict[str, Any]]:
        """Return a bounded sample only when explicitly requested by onboarding."""

        if not 1 <= limit <= 20:
            raise ValueError("Sample limit must be between 1 and 20.")
        parts = table.split(".")
        if len(parts) != 2:
            raise ValueError("Table must be written as schema.table.")
        schema_name, table_name = (_quote_identifier(part) for part in parts)
        result = self._run_json(
            f"SELECT TOP ({limit}) * FROM {schema_name}.{table_name} FOR JSON PATH, INCLUDE_NULL_VALUES;"
        )
        if not isinstance(result, list):
            raise SqlServerConnectorError("SQL Server sample did not return a JSON array.")
        return result


@dataclass(slots=True)
class SqlServerOperationalFactConnector:
    """Read recent operational lines using JAKASII's discovered model.

    Query plans are derived from the persisted schema catalog, awareness role
    candidates, inferred joins, and canonical mapping proposals. No store table
    or column names are embedded in this connector. Results are deliberately
    narrow: product code, quantity, pack size, destination, timestamp and
    hashed source identity. Customer, supplier, staff, price and amount fields
    are never selected.
    """

    server: str
    database: str
    store_id: str
    store_name: str
    schema_catalog: dict[str, Any]
    awareness: dict[str, Any]
    profile: dict[str, Any]
    limit_per_operation: int = 5
    operation_types: tuple[str, ...] = ("purchase", "sale")
    errors: list[str] = field(default_factory=list, init=False)

    @property
    def name(self) -> str:
        return "sqlserver_operational_facts"

    @staticmethod
    def _normalized(value: str) -> str:
        return re.sub(r"[^a-z0-9]", "", value.lower())

    def _sql_source(self) -> dict[str, Any]:
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
            raise SqlServerConnectorError("No SQL Server source exists in the persisted schema catalog.")
        return selected[0]

    @staticmethod
    def _table_index(source: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return {
            f"{source['name']}.{table['name']}": table
            for table in source.get("tables", [])
        }

    def _role_table(
        self, role: str, table_index: dict[str, dict[str, Any]], minimum: float
    ) -> tuple[str, dict[str, Any], float] | None:
        for candidate in self.awareness.get("role_candidates", {}).get(role, []):
            path = str(candidate.get("source_path", ""))
            confidence = float(candidate.get("confidence", 0.0))
            if path in table_index and confidence >= minimum and (candidate.get("row_count") or 0) > 0:
                return path, table_index[path], confidence
        return None

    def _relationship(
        self, left: str, right: str, minimum: float = 0.80
    ) -> tuple[str, str, float] | None:
        relationships = [
            *self.awareness.get("declared_relationships", []),
            *self.awareness.get("inferred_relationships", []),
        ]
        ranked = sorted(
            relationships,
            key=lambda item: float(item.get("confidence", 0.0)),
            reverse=True,
        )
        for relation in ranked:
            confidence = float(relation.get("confidence", 0.0))
            if confidence < minimum:
                continue
            if relation.get("from_table") == left and relation.get("to_table") == right:
                return str(relation["from_column"]), str(relation["to_column"]), confidence
            if relation.get("from_table") == right and relation.get("to_table") == left:
                return str(relation["to_column"]), str(relation["from_column"]), confidence
        return None

    def _mapped_column(
        self, canonical: str, table_path: str, table: dict[str, Any]
    ) -> tuple[str, float, bool] | None:
        prefix = f"{table_path}."
        columns = {str(item.get("name")) for item in table.get("columns", [])}
        for mapping in self.profile.get("mappings", []):
            path = str(mapping.get("source_path", ""))
            if mapping.get("canonical_field") != canonical or not path.startswith(prefix):
                continue
            column = path[len(prefix) :]
            if column in columns:
                return (
                    column,
                    float(mapping.get("confidence", 0.0)),
                    bool(mapping.get("verified")),
                )
        return None

    def _signature_column(
        self, table: dict[str, Any], exact: tuple[str, ...], contains: tuple[str, ...] = ()
    ) -> str | None:
        columns = [(str(item.get("name")), self._normalized(str(item.get("name", "")))) for item in table.get("columns", [])]
        for wanted in exact:
            match = next((name for name, normalized in columns if normalized == wanted), None)
            if match:
                return match
        return next(
            (
                name
                for name, normalized in columns
                if any(token in normalized for token in contains)
            ),
            None,
        )

    @staticmethod
    def _quote_table(table: dict[str, Any]) -> str:
        parts = str(table.get("name", "")).split(".")
        if len(parts) != 2:
            raise ValueError("SQL Server catalog tables must be schema.table paths.")
        return ".".join(_quote_identifier(part) for part in parts)

    @staticmethod
    def _number(value: Any) -> int | float | None:
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError):
            return None
        return int(number) if number.is_integer() else number

    @staticmethod
    def _occurred_at(date_value: Any, time_value: Any) -> str:
        date_text = str(date_value or "").strip()
        time_text = str(time_value or "").strip()
        if time_text and len(time_text) >= 10 and time_text[:4].isdigit():
            return time_text
        if date_text and time_text:
            return f"{date_text[:10]}T{time_text[-12:]}"
        return date_text or time_text or "unknown"

    def _line_facts(self, operation: str) -> list[dict[str, Any]]:
        source = self._sql_source()
        tables = self._table_index(source)
        header_role = self._role_table(f"{operation}_header", tables, 0.80)
        line_role = self._role_table(f"{operation}_line", tables, 0.80)
        product_role = self._role_table("product_catalog", tables, 0.80)
        if not (header_role and line_role and product_role):
            raise SqlServerConnectorError(f"Awareness lacks a reliable {operation} header/line/product plan.")
        header_path, header, header_confidence = header_role
        line_path, line, line_confidence = line_role
        product_path, product, product_confidence = product_role
        header_join = self._relationship(header_path, line_path)
        product_join = self._relationship(line_path, product_path)
        if not header_join or not product_join:
            raise SqlServerConnectorError(f"Awareness lacks reliable joins for {operation} operational facts.")
        header_column, line_header_column, header_join_confidence = header_join
        line_product_column, product_column, product_join_confidence = product_join

        date_column = self._signature_column(
            header,
            (f"{operation}date", "transactiondate", "businessdate", "date"),
            ("date", "createdat", "occurredat"),
        )
        time_column = self._signature_column(
            header,
            (f"{operation}time", "transactiontime", "time"),
            ("time",),
        )
        quantity_mapping = self._mapped_column(f"{operation}.quantity", line_path, line)
        quantity_column = quantity_mapping[0] if quantity_mapping else self._signature_column(
            line, ("qty", "quantity", "soldqty", "receivedqty"), ("quantity",)
        )
        identity_mapping = self._mapped_column("product.identity", product_path, product)
        pack_mapping = self._mapped_column("product.pack_size", product_path, product)
        line_identity = next(
            (
                str(column.get("name"))
                for column in line.get("columns", [])
                if column.get("primary_key")
            ),
            None,
        ) or self._signature_column(line, (f"{operation}dtlid", "lineid", "detailid"), ("dtlid", "lineid"))
        destination_column = self._signature_column(
            line,
            ("destinationid", "locationid", "godownid", "gowdownid", "warehouseid", "shelfid"),
            ("destination", "location", "godown", "gowdown", "warehouse", "shelf"),
        )
        if not (date_column and quantity_column and identity_mapping and line_identity):
            raise SqlServerConnectorError(f"The {operation} plan is missing date, quantity, product identity or line identity.")

        product_identity, identity_confidence, identity_verified = identity_mapping
        pack_column = pack_mapping[0] if pack_mapping else None
        select_parts = [
            f"CONVERT(nvarchar(128), h.{_quote_identifier(header_column)}) AS header_record_id",
            f"CONVERT(nvarchar(128), d.{_quote_identifier(line_identity)}) AS line_record_id",
            f"CONVERT(varchar(33), h.{_quote_identifier(date_column)}, 126) AS event_date",
            f"CONVERT(nvarchar(256), p.{_quote_identifier(product_identity)}) AS product_id",
            f"d.{_quote_identifier(quantity_column)} AS quantity",
        ]
        if time_column:
            select_parts.append(
                f"CONVERT(varchar(33), h.{_quote_identifier(time_column)}, 126) AS event_time"
            )
        if pack_column:
            select_parts.append(f"p.{_quote_identifier(pack_column)} AS pack_size")
        if destination_column:
            select_parts.append(
                f"CONVERT(nvarchar(128), d.{_quote_identifier(destination_column)}) AS destination_id"
            )
        order = f"h.{_quote_identifier(date_column)} DESC"
        if time_column:
            order += f", h.{_quote_identifier(time_column)} DESC"
        limit = max(1, min(int(self.limit_per_operation), 100))
        query = (
            f"SELECT TOP ({limit}) {', '.join(select_parts)} "
            f"FROM {self._quote_table(header)} AS h "
            f"INNER JOIN {self._quote_table(line)} AS d "
            f"ON d.{_quote_identifier(line_header_column)} = h.{_quote_identifier(header_column)} "
            f"INNER JOIN {self._quote_table(product)} AS p "
            f"ON p.{_quote_identifier(product_column)} = d.{_quote_identifier(line_product_column)} "
            f"ORDER BY {order} FOR JSON PATH, INCLUDE_NULL_VALUES;"
        )
        runner = SqlServerConnector(
            self.server, self.database, self.store_id, self.store_name
        )
        rows = runner._run_json(query)
        facts: list[dict[str, Any]] = []
        structural_confidence = min(
            header_confidence,
            line_confidence,
            product_confidence,
            header_join_confidence,
            product_join_confidence,
            identity_confidence,
            quantity_mapping[1] if quantity_mapping else 0.78,
        )
        for row in rows:
            row = dict(row)
            header_id = row.pop("header_record_id", None)
            line_id = row.pop("line_record_id", None)
            record_hash = hashlib.sha256(
                f"{operation}|{header_id}|{line_id}".encode("utf-8")
            ).hexdigest()[:20]
            occurred_at = self._occurred_at(row.pop("event_date", None), row.pop("event_time", None))
            pack_size = self._number(row.get("pack_size"))
            payload = {
                "operation_type": f"{operation}_line",
                "product_id": str(row.get("product_id") or "").strip(),
                "quantity": self._number(row.get("quantity")),
                "pack_size": pack_size if pack_size and pack_size > 0 else None,
                "destination_id": row.get("destination_id"),
                "source_record_hash": record_hash,
                "structural_confidence": round(structural_confidence, 2),
                "mapping_verified": bool(
                    identity_verified
                    and quantity_mapping
                    and quantity_mapping[2]
                    and (not pack_mapping or pack_mapping[2])
                ),
                "interpretation": "candidate_system_fact_from_discovered_schema",
            }
            facts.append(
                {
                    "external_id": f"sql-operation:{operation}:{record_hash}",
                    "occurred_at": occurred_at,
                    "kind": "system_record",
                    "confidence": round(structural_confidence, 2),
                    "payload": payload,
                }
            )
        return facts

    def poll(self) -> Iterable[dict[str, Any]]:
        self.errors.clear()
        facts: list[dict[str, Any]] = []
        for operation in self.operation_types:
            if operation not in {"purchase", "sale"}:
                self.errors.append(f"Unsupported operation type: {operation}")
                continue
            try:
                facts.extend(self._line_facts(operation))
            except (SqlServerConnectorError, ValueError) as exc:
                self.errors.append(f"{operation}: {exc}")
        facts.sort(key=lambda item: item.get("occurred_at", ""))
        return facts


@dataclass(slots=True)
class LocalCameraSystemConnector:
    """Discover an authorized local camera configuration and event collector.

    Discovery scans JSON configuration shapes and SQLite schemas only. Secret
    fields, RTSP URLs, video frames, event rows, and biometric data are never
    returned. A TCP reachability probe checks the configured device port without
    authenticating or opening a stream.
    """

    root: str | Path
    store_id: str
    store_name: str
    probe_timeout_seconds: float = 0.75

    @property
    def name(self) -> str:
        return "local_camera_system"

    @staticmethod
    def _json_type(value: Any) -> str:
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int):
            return "integer"
        if isinstance(value, float):
            return "number"
        return "string"

    def _find_camera_config(self) -> tuple[Path, dict[str, Any], list[dict[str, Any]]]:
        root = Path(self.root).resolve()
        candidates: list[tuple[int, Path, dict[str, Any], list[dict[str, Any]]]] = []
        for path in sorted(root.glob("*.json")):
            try:
                if path.stat().st_size > 1_000_000:
                    continue
                document = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                continue
            if not isinstance(document, dict):
                continue
            cameras = document.get("cameras")
            if not isinstance(cameras, list) or not cameras:
                continue
            safe_channels = []
            for camera in cameras:
                if not isinstance(camera, dict) or "channel" not in camera:
                    continue
                safe_channels.append(
                    {
                        key: camera[key]
                        for key in ("channel", "name", "role", "enabled", "entry_counter")
                        if key in camera
                    }
                )
            if safe_channels:
                score = len(safe_channels) + sum(
                    1 for key in ("dvr_ip", "dvr_port", "store_name") if key in document
                )
                candidates.append((score, path, document, safe_channels))
        if not candidates:
            raise FileNotFoundError(
                f"No camera-channel configuration was discovered under {root}."
            )
        _score, path, document, channels = max(candidates, key=lambda item: item[0])
        return path, document, channels

    def _probe(self, host: str | None, port: int | None) -> bool | None:
        if not host or not port:
            return None
        try:
            with socket.create_connection((host, int(port)), timeout=self.probe_timeout_seconds):
                return True
        except OSError:
            return False

    def _event_sources(self, root: Path) -> list[dict[str, Any]]:
        sources: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*.sqlite3")):
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                connection.row_factory = sqlite3.Row
                table_names = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                ]
                tables = []
                for table_name in table_names:
                    quoted = '"' + table_name.replace('"', '""') + '"'
                    columns = [dict(row) for row in connection.execute(f"PRAGMA table_info({quoted})")]
                    normalized = {
                        re.sub(r"[^a-z0-9]", "", str(column["name"]).lower())
                        for column in columns
                    }
                    camera_signal = any(
                        any(token in column for token in ("camera", "channel", "snapshot", "detector"))
                        for column in normalized
                    )
                    event_signal = any(
                        any(token in column for token in ("startedat", "endedat", "occurredat", "eventid"))
                        for column in normalized
                    )
                    if not (camera_signal and event_signal):
                        continue
                    row_count = int(connection.execute(f"SELECT COUNT(*) FROM {quoted}").fetchone()[0])
                    tables.append(
                        {
                            "name": table_name,
                            "row_count": row_count,
                            "columns": [
                                {
                                    "name": str(column["name"]),
                                    "type": str(column["type"] or "unknown"),
                                    "nullable": not bool(column["notnull"]),
                                    "primary_key": bool(column["pk"]),
                                    "samples": [],
                                }
                                for column in columns
                            ],
                        }
                    )
                if tables:
                    sources.append(
                        {
                            "name": re.sub(r"[^A-Za-z0-9_-]+", "_", f"camera_events_{path.stem}"),
                            "kind": "sqlite_camera_events",
                            "path": str(path),
                            "access": "read_only_metadata",
                            "tables": tables,
                        }
                    )
            except (OSError, sqlite3.DatabaseError):
                continue
            finally:
                if connection is not None:
                    connection.close()
        return sources

    def inspect_schema(self) -> dict[str, Any]:
        root = Path(self.root).resolve()
        config_path, config, channels = self._find_camera_config()
        host = config.get("dvr_ip") or config.get("host")
        port_value = config.get("dvr_port") or config.get("port")
        port = int(port_value) if isinstance(port_value, (int, str)) and str(port_value).isdigit() else None
        column_names = sorted({key for channel in channels for key in channel})
        camera_source = {
            "name": self.name,
            "kind": "camera_registry",
            "path": str(config_path),
            "access": "metadata_only",
            "device": {
                "host": str(host) if host else None,
                "port": port,
                "reachable": self._probe(str(host) if host else None, port),
            },
            "tables": [
                {
                    "name": "camera_channels",
                    "row_count": len(channels),
                    "columns": [
                        {
                            "name": column,
                            "type": self._json_type(
                                next(channel[column] for channel in channels if column in channel)
                            ),
                            "nullable": any(column not in channel for channel in channels),
                            "primary_key": column == "channel",
                            "samples": [],
                        }
                        for column in column_names
                    ],
                }
            ],
            "entities": {"camera_channels": channels},
        }
        if "role" in column_names:
            camera_source["semantic_contracts"] = [
                {
                    "canonical_field": "camera.zone",
                    "table": "camera_channels",
                    "column": "role",
                    "authority": "authorized_connector_contract",
                }
            ]
        return {
            "store_id": self.store_id,
            "name": self.store_name,
            "sources": [camera_source, *self._event_sources(root)],
            "schema_source": {
                "connector": "local_camera_system",
                "root": str(root),
                "configuration": str(config_path),
            },
            "requires_mapping_confirmation": True,
        }

    def sample_records(self, table: str, limit: int = 5) -> list[dict[str, Any]]:
        raise PermissionError("Automatic camera discovery never returns event or video rows.")


@dataclass(slots=True)
class FirestoreStaffRoleConnector:
    """Discover staff routing roles without copying staff identities.

    The service account authorizes a read-only onboarding query but its path and
    contents are never returned by ``inspect_schema``. Only normalized role
    names and aggregate counts leave this connector; UIDs, names, emails,
    photos, attendance locations and document contents stay in Firestore.
    """

    service_account_path: str | Path
    store_id: str
    store_name: str
    collection_name: str = "userstaff"
    client_factory: Any | None = None

    @property
    def name(self) -> str:
        return "firestore_staff_roles"

    @staticmethod
    def _normalize_role(value: Any) -> str:
        role = str(value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "staff": "shelfer",
            "shelf_staff": "shelfer",
            "shelf": "shelfer",
            "godown": "godown_incharge",
            "data_entry_operator": "deo",
            "product_assistance": "product_manager",
            "product_assistant": "product_manager",
            "productmanager": "product_manager",
            "purchase_accounts": "purchase_incharge",
            "purchase_account": "purchase_incharge",
        }
        return aliases.get(role, role) or "unassigned"

    def _client(self) -> Any:
        if self.client_factory is not None:
            return self.client_factory()
        account_path = Path(self.service_account_path).expanduser().resolve()
        if not account_path.is_file():
            raise FirestoreConnectorError("The authorized Firestore service-account file was not found.")
        try:
            import firebase_admin
            from firebase_admin import credentials, firestore
        except ImportError as exc:
            raise FirestoreConnectorError(
                "Firestore support is optional. Install JAKASII Ops with the `firestore` extra."
            ) from exc
        app_name = f"jakasii-{hashlib.sha256(str(account_path).encode()).hexdigest()[:12]}"
        try:
            app = firebase_admin.get_app(app_name)
        except ValueError:
            app = firebase_admin.initialize_app(
                credentials.Certificate(str(account_path)), name=app_name
            )
        return firestore.client(app=app)

    def inspect_schema(self) -> dict[str, Any]:
        try:
            documents = self._client().collection(self.collection_name).select(["role"]).stream()
            counts = Counter(
                self._normalize_role((document.to_dict() or {}).get("role"))
                for document in documents
            )
        except FirestoreConnectorError:
            raise
        except Exception as exc:
            raise FirestoreConnectorError(
                "Authorized Firestore staff-role discovery failed. No staff data was persisted."
            ) from exc
        roles = [
            {"role": role, "count": count}
            for role, count in sorted(counts.items())
        ]
        return {
            "store_id": self.store_id,
            "name": self.store_name,
            "sources": [
                {
                    "name": self.name,
                    "kind": "firestore_staff_roles",
                    "access": "read_only_aggregate",
                    "tables": [
                        {
                            "name": "staff_directory",
                            "row_count": sum(counts.values()),
                            "columns": [
                                {
                                    "name": "role",
                                    "type": "string",
                                    "nullable": "unassigned" in counts,
                                    "primary_key": False,
                                    "samples": [],
                                }
                            ],
                        }
                    ],
                    "entities": {"staff_roles": roles},
                    "semantic_contracts": [
                        {
                            "canonical_field": "staff.role",
                            "table": "staff_directory",
                            "column": "role",
                            "authority": "authorized_connector_contract",
                        }
                    ],
                }
            ],
            "schema_source": {
                "connector": "firestore_staff_roles",
                "authentication": "service_account",
                "privacy": "aggregate_roles_only",
            },
            "requires_mapping_confirmation": True,
        }

    def sample_records(self, table: str, limit: int = 5) -> list[dict[str, Any]]:
        raise PermissionError("Staff discovery never exposes staff document rows.")


@dataclass(slots=True)
class CompositeSchemaConnector:
    """Merge multiple read-only connector discoveries for one store."""

    connectors: tuple[SchemaConnector, ...]
    store_id: str
    store_name: str
    name: str = "composite_store_discovery"

    def inspect_schema(self) -> dict[str, Any]:
        sources: list[dict[str, Any]] = []
        origins: list[dict[str, Any]] = []
        requires_confirmation = False
        for connector in self.connectors:
            document = connector.inspect_schema()
            if document.get("store_id") != self.store_id:
                raise ValueError("Composite connectors must use the same store_id.")
            sources.extend(document.get("sources", []))
            source = document.get("schema_source")
            if source:
                origins.append(source)
            requires_confirmation = requires_confirmation or bool(
                document.get("requires_mapping_confirmation")
            )
        if not sources:
            raise ValueError("Composite discovery found no sources.")
        return {
            "store_id": self.store_id,
            "name": self.store_name,
            "sources": sources,
            "schema_source": {"connector": "composite", "origins": origins},
            "requires_mapping_confirmation": requires_confirmation,
        }

    def sample_records(self, table: str, limit: int = 5) -> list[dict[str, Any]]:
        raise PermissionError("Composite discovery does not expose automatic row sampling.")


@dataclass(slots=True)
class LocalCameraEventConnector:
    """Read safe observation metadata from an existing local camera collector."""

    root: str | Path
    limit: int = 100
    name: str = "local_camera_events"

    @staticmethod
    def _quote_sqlite_identifier(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    @staticmethod
    def _pick(columns: dict[str, str], candidates: tuple[str, ...]) -> str | None:
        return next((columns[name] for name in candidates if name in columns), None)

    def poll(self) -> Iterable[dict[str, Any]]:
        root = Path(self.root).resolve()
        events: list[dict[str, Any]] = []
        for path in sorted(root.rglob("*.sqlite3")):
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                connection.row_factory = sqlite3.Row
                table_names = [
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                ]
                for table_name in table_names:
                    quoted_table = self._quote_sqlite_identifier(table_name)
                    info = [dict(row) for row in connection.execute(f"PRAGMA table_info({quoted_table})")]
                    columns = {
                        re.sub(r"[^a-z0-9]", "", str(column["name"]).lower()): str(column["name"])
                        for column in info
                    }
                    event_id = self._pick(columns, ("eventid", "observationid", "detectionid"))
                    channel = self._pick(columns, ("camerachannel", "channel", "cameraid"))
                    started = self._pick(columns, ("startedat", "occurredat", "timestamp", "createdat"))
                    if not (event_id and channel and started):
                        continue
                    optional = {
                        "camera_name": self._pick(columns, ("cameraname", "channelname")),
                        "ended_at": self._pick(columns, ("endedat", "finishedat")),
                        "max_people": self._pick(columns, ("maxpeople", "peoplecount", "personcount")),
                        "detector": self._pick(columns, ("detector", "model", "detectortype")),
                    }
                    selections = [
                        f"{self._quote_sqlite_identifier(event_id)} AS external_event_id",
                        f"{self._quote_sqlite_identifier(channel)} AS camera_channel",
                        f"{self._quote_sqlite_identifier(started)} AS occurred_at",
                    ]
                    selections.extend(
                        f"{self._quote_sqlite_identifier(source)} AS {alias}"
                        for alias, source in optional.items()
                        if source
                    )
                    query = (
                        f"SELECT {', '.join(selections)} FROM {quoted_table} "
                        f"ORDER BY {self._quote_sqlite_identifier(started)} DESC LIMIT ?"
                    )
                    for row in connection.execute(query, (max(1, min(self.limit, 1000)),)).fetchall():
                        record = dict(row)
                        external_id = str(record.pop("external_event_id"))
                        occurred_at = str(record.pop("occurred_at"))
                        events.append(
                            {
                                "external_id": f"{path.name}:{table_name}:{external_id}",
                                "occurred_at": occurred_at,
                                "payload": {
                                    "camera_event_id": external_id,
                                    "collector": path.name,
                                    **record,
                                    "camera_claim": "activity_observation_only",
                                },
                                "confidence": 0.90,
                            }
                        )
            except (OSError, sqlite3.DatabaseError):
                continue
            finally:
                if connection is not None:
                    connection.close()
        events.sort(key=lambda item: item.get("occurred_at", ""))
        return events


@dataclass(slots=True)
class LocalVerifiedOperationConnector:
    """Import human labels and SQL facts emitted by an existing collector.

    Camera observations, human confirmations and system records remain distinct
    evidence kinds. Personal staff fields, product names, notes, monetary
    amounts and raw business document IDs are deliberately excluded.
    """

    root: str | Path
    limit: int = 100
    name: str = "local_verified_operations"

    @staticmethod
    def _record_hash(*values: Any) -> str:
        material = "|".join(str(value or "") for value in values)
        return hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]

    def poll(self) -> Iterable[dict[str, Any]]:
        root = Path(self.root).resolve()
        evidence: list[dict[str, Any]] = []
        bounded_limit = max(1, min(self.limit, 1000))
        for path in sorted(root.rglob("*.sqlite3")):
            connection: sqlite3.Connection | None = None
            try:
                connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
                connection.row_factory = sqlite3.Row
                tables = {
                    str(row[0])
                    for row in connection.execute(
                        "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                    ).fetchall()
                }
                if "verified_labels" in tables:
                    rows = connection.execute(
                        "SELECT event_id, action, product_sku, quantity, source_zone, "
                        "destination_shelf, verified_at FROM verified_labels "
                        "ORDER BY verified_at DESC LIMIT ?",
                        (bounded_limit,),
                    ).fetchall()
                    for row in rows:
                        item = dict(row)
                        event_id = str(item.pop("event_id"))
                        occurred_at = str(item.pop("verified_at"))
                        evidence.append(
                            {
                                "external_id": f"{path.name}:verified_label:{event_id}",
                                "occurred_at": occurred_at,
                                "kind": "human_confirmation",
                                "confidence": 1.0,
                                "payload": {
                                    "camera_event_id": event_id,
                                    **item,
                                    "verification_method": "collector_human_label",
                                },
                            }
                        )
                if "sql_facts" in tables:
                    rows = connection.execute(
                        "SELECT fact_key, fact_type, occurred_at, document_id, line_id, "
                        "product_sku, quantity FROM sql_facts "
                        "ORDER BY occurred_at DESC LIMIT ?",
                        (bounded_limit,),
                    ).fetchall()
                    for row in rows:
                        item = dict(row)
                        fact_key = str(item.pop("fact_key"))
                        occurred_at = str(item.pop("occurred_at"))
                        document_id = item.pop("document_id", None)
                        line_id = item.pop("line_id", None)
                        evidence.append(
                            {
                                "external_id": f"{path.name}:sql_fact:{fact_key}",
                                "occurred_at": occurred_at,
                                "kind": "system_record",
                                "confidence": 1.0,
                                "payload": {
                                    "fact_key": fact_key,
                                    **item,
                                    "source_record_hash": self._record_hash(document_id, line_id),
                                },
                            }
                        )
            except (OSError, sqlite3.DatabaseError):
                continue
            finally:
                if connection is not None:
                    connection.close()
        evidence.sort(key=lambda item: item.get("occurred_at", ""))
        return evidence
