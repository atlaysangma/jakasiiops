from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from typing import Any

from .agent import StoreAgent, StoreAgentConfig
from .api import serve
from .brain import JakasiiOpsBrain
from .bootstrap import LocalStoreBootstrapper
from .connectors import (
    CompositeSchemaConnector,
    FirestoreStaffRoleConnector,
    LocalCameraEventConnector,
    LocalCameraSystemConnector,
    LocalVerifiedOperationConnector,
    SqlServerConnector,
    SqlServerOperationalFactConnector,
)
from .credentials import (
    configure_manifest_credentials,
    hydrate_manifest_environment,
)
from .reasoning import DeterministicReasoner, OllamaReasoner
from .validation import SqlServerMappingValidator


def dump(payload: Any) -> None:
    print(json.dumps(payload, indent=2, ensure_ascii=False, default=str))


def make_brain(args: argparse.Namespace) -> JakasiiOpsBrain:
    reasoner = OllamaReasoner(model=args.model) if args.provider == "ollama" else DeterministicReasoner()
    return JakasiiOpsBrain(args.data_root, reasoner)


def run_demo(args: argparse.Namespace) -> int:
    fixture_root = Path(__file__).resolve().parents[2] / "fixtures"
    brain = make_brain(args)
    schema_path = fixture_root / args.fixture / "schema.json"
    onboarding = brain.onboard(schema_path)
    answers = json.loads((fixture_root / args.fixture / "answers.json").read_text(encoding="utf-8"))
    for question in list(onboarding["questions"]):
        answer = answers.get(question["key"])
        if answer is None:
            continue
        brain.answer_setup(onboarding["profile"]["store_id"], question["id"], answer, "demo_owner")

    store_id = onboarding["profile"]["store_id"]
    camera = brain.record_evidence(
        store_id,
        "observation",
        "synthetic_camera_event",
        {"zone": "receiving_bay", "activity": "cartons_unloaded", "count_is_not_claimed": True},
        0.78,
    )
    purchase = brain.record_evidence(
        store_id,
        "system_record",
        "synthetic_purchase_export",
        {"product_id": "SKU-TEA-250", "cartons": 1, "pack_size": 24, "loose_pieces": 5},
        1.0,
    )
    result = brain.process_event(
        store_id,
        "receiving",
        {
            "product_id": "SKU-TEA-250",
            "cartons": 1,
            "pack_size": 24,
            "loose_pieces": 5,
            "total_base_units": 29,
            "destination_id": None,
            "receiver_confirmed": False,
        },
        [camera["id"], purchase["id"]],
    )
    dump(
        {
            "onboarding": brain.readiness(store_id),
            "operational_result": result,
            "status": brain.status(store_id),
            "memory_root": str((Path(args.data_root) / "store-memory" / store_id).resolve()),
        }
    )
    brain.close()
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="JAKASII Ops headless brain")
    parser.add_argument("--data-root", default="data", help="Local state and store-memory directory")
    parser.add_argument("--provider", choices=("deterministic", "ollama"), default="deterministic")
    parser.add_argument("--model", default="qwen2.5:7b", help="Ollama model when --provider=ollama")
    sub = parser.add_subparsers(dest="command", required=True)

    serve_parser = sub.add_parser("serve", help="Run the headless JSON API")
    serve_parser.add_argument("--host", default="127.0.0.1")
    serve_parser.add_argument("--port", type=int, default=8765)

    onboard_parser = sub.add_parser("onboard", help="Inspect a synthetic/exported schema document")
    onboard_parser.add_argument("schema_path")

    sql_parser = sub.add_parser(
        "onboard-sqlserver",
        help="Discover and onboard a SQL Server database through read-only Windows authentication",
    )
    sql_parser.add_argument("--server", default="localhost")
    sql_parser.add_argument("--database", required=True)
    sql_parser.add_argument("--store-id", required=True)
    sql_parser.add_argument("--store-name", required=True)

    store_parser = sub.add_parser(
        "onboard-store",
        help="Discover SQL Server plus an authorized local camera/collector directory",
    )
    store_parser.add_argument("--server", default="localhost")
    store_parser.add_argument("--database", required=True)
    store_parser.add_argument("--camera-root", required=True)
    store_parser.add_argument(
        "--staff-service-account",
        help="Optional authorized Firestore service-account file; the path is never persisted",
    )
    store_parser.add_argument("--store-id", required=True)
    store_parser.add_argument("--store-name", required=True)

    status_parser = sub.add_parser("status", help="Show readiness and operational counts")
    status_parser.add_argument("store_id")

    actions_parser = sub.add_parser(
        "actions", help="List approval-gated action requests"
    )
    actions_parser.add_argument("store_id")

    approve_parser = sub.add_parser(
        "approve-action", help="Record an owner's approval for one pending action"
    )
    approve_parser.add_argument("store_id")
    approve_parser.add_argument("action_id")
    approve_parser.add_argument("--actor", required=True)

    awareness_parser = sub.add_parser("awareness", help="Show the persisted store-awareness model")
    awareness_parser.add_argument("store_id")

    snapshot_parser = sub.add_parser(
        "snapshot", help="Summarize evidence coverage, operational events, and open role work"
    )
    snapshot_parser.add_argument("store_id")
    snapshot_parser.add_argument("--window-minutes", type=int, default=15)

    proofs_parser = sub.add_parser(
        "proofs", help="Show strict real-operation proof progress"
    )
    proofs_parser.add_argument("store_id")
    proofs_parser.add_argument("--window-minutes", type=int, default=15)

    camera_events_parser = sub.add_parser(
        "ingest-camera-events",
        help="Import safe observation metadata from an authorized local camera collector",
    )
    camera_events_parser.add_argument("--camera-root", required=True)
    camera_events_parser.add_argument("--store-id", required=True)
    camera_events_parser.add_argument("--limit", type=int, default=100)

    verified_parser = sub.add_parser(
        "ingest-verified-operations",
        help="Import privacy-minimized human labels and SQL facts from a local collector",
    )
    verified_parser.add_argument("--collector-root", required=True)
    verified_parser.add_argument("--store-id", required=True)
    verified_parser.add_argument("--limit", type=int, default=100)

    sql_cycle_parser = sub.add_parser(
        "run-sql-cycle",
        help="Derive recent purchase/sale facts from learned schema and route verification work",
    )
    sql_cycle_parser.add_argument("--server", default="localhost")
    sql_cycle_parser.add_argument("--database", required=True)
    sql_cycle_parser.add_argument("--store-id", required=True)
    sql_cycle_parser.add_argument("--store-name", required=True)
    sql_cycle_parser.add_argument("--limit", type=int, default=5)

    validation_parser = sub.add_parser(
        "validate-sql-mappings",
        help="Validate learned SQL meanings using aggregate shape checks only",
    )
    validation_parser.add_argument("--server", default="localhost")
    validation_parser.add_argument("--database", required=True)
    validation_parser.add_argument("--store-id", required=True)
    validation_parser.add_argument("--store-name", required=True)

    watch_parser = sub.add_parser(
        "watch-store",
        help="Continuously rescan and observe an authorized store without writing to source systems",
    )
    watch_parser.add_argument("--server", default="localhost")
    watch_parser.add_argument("--database", required=True)
    watch_parser.add_argument("--camera-root", required=True)
    watch_parser.add_argument("--staff-service-account")
    watch_parser.add_argument("--store-id", required=True)
    watch_parser.add_argument("--store-name", required=True)
    watch_parser.add_argument("--poll-seconds", type=float, default=30.0)
    watch_parser.add_argument("--rescan-seconds", type=float, default=3600.0)
    watch_parser.add_argument("--limit", type=int, default=10)
    watch_parser.add_argument(
        "--backfill-existing",
        action="store_true",
        help="Process existing recent source records on first start instead of baselining them",
    )
    watch_parser.add_argument(
        "--max-cycles",
        type=int,
        help="Stop after this many cycles; omit for continuous main-server operation",
    )

    bootstrap_parser = sub.add_parser(
        "bootstrap-store",
        help="Discover the best local SQL database and camera collector, then onboard them",
    )
    bootstrap_parser.add_argument("--store-id", required=True)
    bootstrap_parser.add_argument("--store-name", required=True)
    bootstrap_parser.add_argument("--scan-root", action="append")
    bootstrap_parser.add_argument("--server-candidate", action="append")
    bootstrap_parser.add_argument("--staff-service-account")

    auto_watch_parser = sub.add_parser(
        "auto-watch-store",
        help="Autonomously discover local store connections and run the continuous agent",
    )
    auto_watch_parser.add_argument("--store-id", required=True)
    auto_watch_parser.add_argument("--store-name", required=True)
    auto_watch_parser.add_argument("--scan-root", action="append")
    auto_watch_parser.add_argument("--server-candidate", action="append")
    auto_watch_parser.add_argument("--staff-service-account")
    auto_watch_parser.add_argument("--poll-seconds", type=float, default=30.0)
    auto_watch_parser.add_argument("--rescan-seconds", type=float, default=3600.0)
    auto_watch_parser.add_argument("--limit", type=int, default=10)
    auto_watch_parser.add_argument("--backfill-existing", action="store_true")
    auto_watch_parser.add_argument("--max-cycles", type=int)

    access_parser = sub.add_parser(
        "configure-camera-access",
        help="Discover the collector and store its required secrets using a hidden local prompt",
    )
    access_parser.add_argument("--store-id", required=True)
    access_parser.add_argument("--store-name", required=True)
    access_parser.add_argument("--scan-root", action="append")
    access_parser.add_argument("--server-candidate", action="append")

    demo_parser = sub.add_parser("demo", help="Run the complete synthetic onboarding and receiving loop")
    demo_parser.add_argument("--fixture", choices=("legacy_mart", "modern_shop"), default="legacy_mart")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    if args.command == "demo":
        return run_demo(args)
    brain = make_brain(args)
    if args.command == "serve":
        serve(brain, args.host, args.port)
        return 0
    try:
        if args.command == "onboard":
            dump(brain.onboard(args.schema_path))
        elif args.command == "onboard-sqlserver":
            connector = SqlServerConnector(
                server=args.server,
                database=args.database,
                store_id=args.store_id,
                store_name=args.store_name,
            )
            dump(brain.onboard_connector(connector))
        elif args.command == "onboard-store":
            sql_connector = SqlServerConnector(
                server=args.server,
                database=args.database,
                store_id=args.store_id,
                store_name=args.store_name,
            )
            camera_connector = LocalCameraSystemConnector(
                root=args.camera_root,
                store_id=args.store_id,
                store_name=args.store_name,
            )
            connectors = [sql_connector, camera_connector]
            if args.staff_service_account:
                connectors.append(
                    FirestoreStaffRoleConnector(
                        service_account_path=args.staff_service_account,
                        store_id=args.store_id,
                        store_name=args.store_name,
                    )
                )
            dump(
                brain.onboard_connector(
                    CompositeSchemaConnector(
                        connectors=tuple(connectors),
                        store_id=args.store_id,
                        store_name=args.store_name,
                    )
                )
            )
        elif args.command == "status":
            dump(brain.status(args.store_id))
        elif args.command == "actions":
            dump(brain.actions(args.store_id))
        elif args.command == "approve-action":
            dump(brain.approve_action(args.store_id, args.action_id, args.actor))
        elif args.command == "awareness":
            dump(brain.awareness(args.store_id))
        elif args.command == "snapshot":
            dump(brain.operational_snapshot(args.store_id, args.window_minutes))
        elif args.command == "proofs":
            dump(brain.operation_proofs(args.store_id, args.window_minutes))
        elif args.command == "ingest-camera-events":
            dump(
                brain.ingest_evidence_connector(
                    args.store_id,
                    LocalCameraEventConnector(args.camera_root, limit=args.limit),
                )
            )
        elif args.command == "ingest-verified-operations":
            dump(
                brain.ingest_evidence_connector(
                    args.store_id,
                    LocalVerifiedOperationConnector(args.collector_root, limit=args.limit),
                )
            )
        elif args.command == "run-sql-cycle":
            connector = SqlServerOperationalFactConnector(
                server=args.server,
                database=args.database,
                store_id=args.store_id,
                store_name=args.store_name,
                schema_catalog=brain.schema_catalog(args.store_id),
                awareness=brain.awareness(args.store_id),
                profile=brain.profile(args.store_id),
                limit_per_operation=args.limit,
            )
            dump(brain.run_operational_cycle(args.store_id, connector))
        elif args.command == "validate-sql-mappings":
            dump(
                brain.validate_sql_mappings(
                    SqlServerMappingValidator(
                        server=args.server,
                        database=args.database,
                        store_id=args.store_id,
                        store_name=args.store_name,
                        schema_catalog=brain.schema_catalog(args.store_id),
                        awareness=brain.awareness(args.store_id),
                        profile=brain.profile(args.store_id),
                    )
                )
            )
        elif args.command == "watch-store":
            agent = StoreAgent(
                brain,
                StoreAgentConfig(
                    store_id=args.store_id,
                    store_name=args.store_name,
                    server=args.server,
                    database=args.database,
                    camera_root=args.camera_root,
                    staff_service_account=args.staff_service_account,
                    poll_interval_seconds=args.poll_seconds,
                    rescan_interval_seconds=args.rescan_seconds,
                    sql_limit_per_operation=args.limit,
                    backfill_existing=args.backfill_existing,
                ),
            )
            try:
                agent.run(max_cycles=args.max_cycles, on_cycle=dump)
            except KeyboardInterrupt:
                agent.stop()
        elif args.command in {
            "bootstrap-store",
            "auto-watch-store",
            "configure-camera-access",
        }:
            discovery = LocalStoreBootstrapper(
                store_id=args.store_id,
                store_name=args.store_name,
                scan_roots=tuple(args.scan_root or ()),
                server_candidates=tuple(args.server_candidate or ()),
            ).discover()
            brain.record_bootstrap(args.store_id, discovery)
            selection = discovery["selection"]
            manifest = discovery.get("camera_selection", {}).get("runtime_manifest")
            if args.command == "configure-camera-access":
                if not manifest:
                    raise RuntimeError(
                        "The discovered camera collector has no approved runtime manifest."
                    )
                dump(
                    {
                        "credential_setup": configure_manifest_credentials(
                            args.store_id, manifest
                        ),
                        "credential_store": "windows_credential_manager",
                    }
                )
                return 0
            staff_account = args.staff_service_account or os.getenv(
                "JAKASII_FIREBASE_SERVICE_ACCOUNT"
            )
            if args.command == "bootstrap-store":
                connectors = [
                    SqlServerConnector(
                        selection["server"],
                        selection["database"],
                        args.store_id,
                        args.store_name,
                    ),
                    LocalCameraSystemConnector(
                        selection["camera_root"], args.store_id, args.store_name
                    ),
                ]
                if staff_account:
                    connectors.append(
                        FirestoreStaffRoleConnector(
                            staff_account, args.store_id, args.store_name
                        )
                    )
                onboarding = brain.onboard_connector(
                    CompositeSchemaConnector(
                        tuple(connectors), args.store_id, args.store_name
                    )
                )
                validation = brain.validate_sql_mappings(
                    SqlServerMappingValidator(
                        selection["server"],
                        selection["database"],
                        args.store_id,
                        args.store_name,
                        brain.schema_catalog(args.store_id),
                        brain.awareness(args.store_id),
                        brain.profile(args.store_id),
                    )
                )
                dump(
                    {
                        "discovery": discovery,
                        "profile": brain.profile(args.store_id),
                        "questions": brain.questions(args.store_id),
                        "readiness": validation["readiness"],
                        "validated_mappings": validation["promoted"],
                    }
                )
            else:
                credential_status = hydrate_manifest_environment(
                    args.store_id, manifest
                )
                agent = StoreAgent(
                    brain,
                    StoreAgentConfig(
                        store_id=args.store_id,
                        store_name=args.store_name,
                        server=selection["server"],
                        database=selection["database"],
                        camera_root=selection["camera_root"],
                        camera_runtime_manifest=manifest,
                        staff_service_account=staff_account,
                        poll_interval_seconds=args.poll_seconds,
                        rescan_interval_seconds=args.rescan_seconds,
                        sql_limit_per_operation=args.limit,
                        backfill_existing=args.backfill_existing,
                    ),
                )
                dump(
                    {
                        "autonomous_discovery": discovery,
                        "collector_credentials": credential_status,
                        "starting_agent": True,
                    }
                )
                try:
                    agent.run(max_cycles=args.max_cycles, on_cycle=dump)
                except KeyboardInterrupt:
                    agent.stop()
    finally:
        brain.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
