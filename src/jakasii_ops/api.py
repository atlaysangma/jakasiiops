from __future__ import annotations

import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import urlparse

from .brain import JakasiiOpsBrain


class OpsApiHandler(BaseHTTPRequestHandler):
    brain: JakasiiOpsBrain
    server_version = "JAKASII-Ops/0.1"

    def _json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if not length:
            return {}
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def _send(self, payload: Any, status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2, ensure_ascii=False, default=str).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _route_parts(self) -> list[str]:
        return [part for part in urlparse(self.path).path.split("/") if part]

    def do_GET(self) -> None:  # noqa: N802
        try:
            parts = self._route_parts()
            if parts == ["health"]:
                self._send({"status": "ok", "service": "jakasii-ops", "headless": True})
                return
            if len(parts) == 3 and parts[0] == "stores":
                store_id, resource = parts[1], parts[2]
                routes = {
                    "status": lambda: self.brain.status(store_id),
                    "readiness": lambda: self.brain.readiness(store_id),
                    "questions": lambda: self.brain.questions(store_id),
                    "tasks": lambda: self.brain.tasks(store_id, open_only=False),
                    "memory": lambda: self.brain.memory(store_id),
                    "audit": lambda: self.brain.audit(store_id),
                    "actions": lambda: self.brain.actions(store_id),
                }
                if resource in routes:
                    self._send(routes[resource]())
                    return
            self._send({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        except Exception as exc:  # boundary returns safe error text, never secrets
            self._send({"error": type(exc).__name__, "message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def do_POST(self) -> None:  # noqa: N802
        try:
            parts = self._route_parts()
            body = self._json_body()
            if parts == ["onboarding"]:
                self._send(self.brain.onboard(body["schema_path"]), HTTPStatus.CREATED)
                return
            if len(parts) == 3 and parts[0] == "stores" and parts[2] == "evidence":
                self._send(
                    self.brain.record_evidence(
                        parts[1], body["kind"], body["source"], body.get("payload", {}), body.get("confidence", 1.0)
                    ),
                    HTTPStatus.CREATED,
                )
                return
            if len(parts) == 3 and parts[0] == "stores" and parts[2] == "events":
                self._send(
                    self.brain.process_event(
                        parts[1], body["event_type"], body.get("facts", {}), body.get("evidence_ids", [])
                    ),
                    HTTPStatus.CREATED,
                )
                return
            if len(parts) == 3 and parts[0] == "stores" and parts[2] == "actions":
                self._send(
                    self.brain.request_action(
                        parts[1],
                        body["action"],
                        body["target"],
                        body["reason"],
                        body["authority"],
                        body.get("payload", {}),
                        body.get("reversible", False),
                        body.get("data_leaving_device", False),
                    ),
                    HTTPStatus.CREATED,
                )
                return
            if len(parts) == 5 and parts[0] == "stores" and parts[2] == "questions" and parts[4] == "answer":
                self._send(self.brain.answer_setup(parts[1], parts[3], body["answer"], body["actor"]))
                return
            if len(parts) == 5 and parts[0] == "stores" and parts[2] == "tasks" and parts[4] == "answer":
                self._send(self.brain.answer_task(parts[1], parts[3], body.get("answer", {}), body["actor"]))
                return
            if len(parts) == 5 and parts[0] == "stores" and parts[2] == "actions" and parts[4] == "approve":
                self._send(self.brain.approve_action(parts[1], parts[3], body["actor"]))
                return
            self._send({"error": "not_found"}, HTTPStatus.NOT_FOUND)
        except KeyError as exc:
            self._send({"error": "missing_or_unknown", "message": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._send({"error": type(exc).__name__, "message": str(exc)}, HTTPStatus.BAD_REQUEST)

    def log_message(self, format: str, *args: Any) -> None:
        return


def serve(brain: JakasiiOpsBrain, host: str = "127.0.0.1", port: int = 8765) -> None:
    handler = type("ConfiguredOpsApiHandler", (OpsApiHandler,), {"brain": brain})
    server = ThreadingHTTPServer((host, port), handler)
    print(f"JAKASII Ops headless API listening on http://{host}:{port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        brain.close()
