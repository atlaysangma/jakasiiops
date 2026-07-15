from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .api import serve
from .brain import JakasiiOpsBrain
from .reasoning import DeterministicReasoner, OllamaReasoner


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

    status_parser = sub.add_parser("status", help="Show readiness and operational counts")
    status_parser.add_argument("store_id")

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
        elif args.command == "status":
            dump(brain.status(args.store_id))
    finally:
        brain.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
