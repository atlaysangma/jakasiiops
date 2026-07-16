from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .awareness import StoreAwarenessEngine
from .connectors import LocalCameraSystemConnector, SqlServerConnector


IMPORTANT_SQL_ROLES = (
    "product_catalog",
    "purchase_header",
    "purchase_line",
    "sale_header",
    "sale_line",
    "inventory_stock",
    "stock_movement",
)


@dataclass(slots=True)
class LocalStoreBootstrapper:
    """Find a local store database and camera collector from metadata only."""

    store_id: str
    store_name: str
    scan_roots: tuple[str | Path, ...] = ()
    server_candidates: tuple[str, ...] = ()
    max_databases: int = 20
    max_scan_files: int = 5000
    max_scan_depth: int = 3
    database_lister: Callable[[str], list[str]] | None = None
    sql_connector_factory: Callable[[str, str, str, str], Any] | None = None
    camera_connector_factory: Callable[[Path, str, str], Any] | None = None

    @staticmethod
    def _dedupe(values: list[str]) -> list[str]:
        seen: set[str] = set()
        result: list[str] = []
        for value in values:
            key = value.lower()
            if value and key not in seen:
                seen.add(key)
                result.append(value)
        return result

    def _servers(self) -> list[str]:
        if self.server_candidates:
            return self._dedupe(list(self.server_candidates))
        servers = ["localhost"]
        if os.name == "nt":
            try:
                import winreg

                for registry_path in (
                    r"SOFTWARE\Microsoft\Microsoft SQL Server\Instance Names\SQL",
                    r"SOFTWARE\WOW6432Node\Microsoft\Microsoft SQL Server\Instance Names\SQL",
                ):
                    try:
                        key = winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, registry_path)
                    except OSError:
                        continue
                    with key:
                        index = 0
                        while True:
                            try:
                                instance, _value, _kind = winreg.EnumValue(key, index)
                            except OSError:
                                break
                            index += 1
                            servers.append(
                                "localhost"
                                if instance.upper() == "MSSQLSERVER"
                                else f"localhost\\{instance}"
                            )
            except (ImportError, OSError):
                pass
        return self._dedupe(servers)

    def _sql_connector(self, server: str, database: str) -> Any:
        if self.sql_connector_factory:
            return self.sql_connector_factory(
                server, database, self.store_id, self.store_name
            )
        return SqlServerConnector(server, database, self.store_id, self.store_name)

    def _databases(self, server: str) -> list[str]:
        if self.database_lister:
            return self.database_lister(server)[: self.max_databases]
        runner = self._sql_connector(server, "master")
        rows = runner._run_json(
            "SELECT name FROM sys.databases "
            "WHERE database_id > 4 AND state_desc = 'ONLINE' "
            "AND HAS_DBACCESS(name) = 1 ORDER BY name FOR JSON PATH;"
        )
        names = [str(item.get("name", "")).strip() for item in rows]
        return self._dedupe(names)[: self.max_databases]

    @staticmethod
    def _sql_score(document: dict[str, Any]) -> tuple[float, dict[str, Any]]:
        awareness = StoreAwarenessEngine().build(document)
        strengths = {
            role: float(candidates[0].get("confidence", 0.0))
            for role in IMPORTANT_SQL_ROLES
            if (candidates := awareness.get("role_candidates", {}).get(role, []))
        }
        strong = {role: value for role, value in strengths.items() if value >= 0.60}
        table_count = int(awareness.get("table_count", 0))
        column_count = int(awareness.get("column_count", 0))
        score = (
            sum(strong.values()) * 10
            + len(strong) * 5
            + min(table_count, 500) / 100
            + min(column_count, 20_000) / 10_000
        )
        return round(score, 3), {
            "table_count": table_count,
            "column_count": column_count,
            "operational_roles": sorted(strong),
            "role_confidence": {key: round(value, 2) for key, value in sorted(strong.items())},
        }

    def _discover_sql(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        for server in self._servers():
            try:
                databases = self._databases(server)
            except Exception as exc:
                candidates.append(
                    {
                        "server": server,
                        "database": None,
                        "eligible": False,
                        "error": type(exc).__name__,
                    }
                )
                continue
            for database in databases:
                try:
                    document = self._sql_connector(server, database).inspect_schema()
                    score, signals = self._sql_score(document)
                    candidates.append(
                        {
                            "server": server,
                            "database": database,
                            "eligible": bool(signals["operational_roles"]),
                            "score": score,
                            **signals,
                        }
                    )
                except Exception as exc:
                    candidates.append(
                        {
                            "server": server,
                            "database": database,
                            "eligible": False,
                            "error": type(exc).__name__,
                        }
                    )
        eligible = [item for item in candidates if item.get("eligible")]
        if not eligible:
            raise RuntimeError("No accessible operational SQL database was discovered.")
        return max(eligible, key=lambda item: float(item.get("score", 0.0))), candidates

    def _roots(self) -> list[Path]:
        roots = [Path(item).expanduser().resolve() for item in self.scan_roots]
        return roots or [Path.home().resolve()]

    def _camera_directories(self) -> list[Path]:
        excluded = {
            ".git",
            ".venv",
            "node_modules",
            "appdata",
            "windows",
            "$recycle.bin",
        }
        discovered: set[Path] = set()
        inspected = 0
        for root in self._roots():
            if not root.is_dir():
                continue
            for current, directories, files in os.walk(root):
                current_path = Path(current)
                try:
                    depth = len(current_path.relative_to(root).parts)
                except ValueError:
                    continue
                directories[:] = [
                    item
                    for item in directories
                    if item.lower() not in excluded and depth < self.max_scan_depth
                ]
                for filename in files:
                    if inspected >= self.max_scan_files:
                        return sorted(discovered)
                    if not filename.lower().endswith(".json"):
                        continue
                    inspected += 1
                    path = current_path / filename
                    try:
                        if path.stat().st_size > 1_000_000:
                            continue
                        document = json.loads(path.read_text(encoding="utf-8-sig"))
                    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
                        continue
                    cameras = document.get("cameras") if isinstance(document, dict) else None
                    if isinstance(cameras, list) and any(
                        isinstance(item, dict) and "channel" in item for item in cameras
                    ):
                        discovered.add(current_path.resolve())
        return sorted(discovered)

    def _camera_connector(self, root: Path) -> Any:
        if self.camera_connector_factory:
            return self.camera_connector_factory(root, self.store_id, self.store_name)
        return LocalCameraSystemConnector(root, self.store_id, self.store_name)

    @staticmethod
    def _runtime_manifest(root: Path) -> dict[str, Any] | None:
        path = root / "jakasii_collector.json"
        try:
            document = json.loads(path.read_text(encoding="utf-8-sig"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            return None
        if not isinstance(document, dict):
            return None
        command = document.get("command")
        if (
            document.get("protocol") != "jakasii.camera_collector.v1"
            or not isinstance(command, list)
            or len(command) < 2
            or command[0] != "{python}"
            or not all(isinstance(item, str) and item for item in command)
        ):
            return None
        script = Path(command[1])
        if script.is_absolute() or ".." in script.parts or script.suffix.lower() != ".py":
            return None
        resolved_script = (root / script).resolve()
        try:
            resolved_script.relative_to(root.resolve())
        except ValueError:
            return None
        if not resolved_script.is_file():
            return None
        working = Path(str(document.get("working_directory", ".")))
        health = Path(str(document.get("health_file", "")))
        if working.is_absolute() or ".." in working.parts:
            return None
        if health.is_absolute() or ".." in health.parts or not str(health):
            return None
        required = document.get("required_environment", [])
        optional = document.get("optional_environment", [])
        if not all(
            isinstance(items, list)
            and all(
                isinstance(item, str)
                and item
                and item.replace("_", "").isalnum()
                and item.upper() == item
                for item in items
            )
            for items in (required, optional)
        ):
            return None
        return {
            "protocol": document["protocol"],
            "command": command,
            "working_directory": str(working),
            "health_file": str(health),
            "required_environment": required,
            "optional_environment": optional,
            "contains_secret_values": False,
        }

    def _discover_camera(self) -> tuple[dict[str, Any], list[dict[str, Any]]]:
        candidates: list[dict[str, Any]] = []
        for root in self._camera_directories():
            try:
                document = self._camera_connector(root).inspect_schema()
                channels = sum(
                    len(source.get("entities", {}).get("camera_channels", []))
                    for source in document.get("sources", [])
                )
                event_tables = sum(
                    len(source.get("tables", []))
                    for source in document.get("sources", [])
                    if source.get("kind") == "sqlite_camera_events"
                )
                runtime_manifest = self._runtime_manifest(root)
                candidates.append(
                    {
                        "root": str(root),
                        "eligible": channels > 0,
                        "score": channels * 10 + event_tables * 5,
                        "camera_channels": channels,
                        "event_tables": event_tables,
                        "runtime_manifest": runtime_manifest,
                    }
                )
            except Exception as exc:
                candidates.append(
                    {"root": str(root), "eligible": False, "error": type(exc).__name__}
                )
        eligible = [item for item in candidates if item.get("eligible")]
        if not eligible:
            raise RuntimeError("No compatible local camera collector was discovered.")
        return max(eligible, key=lambda item: float(item.get("score", 0.0))), candidates

    def discover(self) -> dict[str, Any]:
        sql, sql_candidates = self._discover_sql()
        camera, camera_candidates = self._discover_camera()
        return {
            "store_id": self.store_id,
            "selection": {
                "server": sql["server"],
                "database": sql["database"],
                "camera_root": camera["root"],
            },
            "basis": "local_metadata_only",
            "sql_selection": sql,
            "camera_selection": camera,
            "candidate_counts": {
                "sql": len(sql_candidates),
                "camera": len(camera_candidates),
            },
            "failures": {
                "sql": sum(1 for item in sql_candidates if item.get("error")),
                "camera": sum(1 for item in camera_candidates if item.get("error")),
            },
        }
