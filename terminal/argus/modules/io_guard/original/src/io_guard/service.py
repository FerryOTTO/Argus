from __future__ import annotations

import argparse
import hmac
import json
import os
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from uuid import uuid4

from io_guard.audit import AuditLogger
from io_guard.pipeline import IOGuard
from io_guard.types import GuardRequest, SourceType


STAGE_TO_SOURCE = {
    "input": SourceType.USER_PROMPT,
    "context": SourceType.RETRIEVAL_CHUNK,
    "output": SourceType.MODEL_OUTPUT,
}


@dataclass
class GuardService:
    """Transport-neutral service facade used by the HTTP handler and tests."""

    guard: IOGuard

    @staticmethod
    def _source_type_for(
        stage: str,
        metadata: dict[str, Any],
    ) -> SourceType:
        """Keep retrieval and tool content on their independently trained heads."""

        if stage != "context":
            return STAGE_TO_SOURCE[stage]

        source = str(metadata.get("source") or "").strip().casefold()
        tool_sources = {
            "tool",
            "tool_call",
            "tool_result",
            "tool-result",
            "toolresult",
        }
        if (
            metadata.get("tool_name")
            or metadata.get("tool_call_id")
            or source in tool_sources
        ):
            return SourceType.TOOL_RESULT
        return SourceType.RETRIEVAL_CHUNK

    def check(self, stage: str, payload: dict[str, Any]) -> dict[str, Any]:
        if stage not in STAGE_TO_SOURCE:
            raise ValueError(f"unsupported stage: {stage}")
        content = payload.get("content")
        if not isinstance(content, str):
            raise ValueError("content must be a string")

        allowed_scopes = payload.get("allowed_data_scopes", [])
        if not isinstance(allowed_scopes, list) or not all(
            isinstance(value, str) for value in allowed_scopes
        ):
            raise ValueError("allowed_data_scopes must be a list of strings")

        metadata = payload.get("metadata", {})
        if not isinstance(metadata, dict):
            raise ValueError("metadata must be an object")

        request = GuardRequest(
            content=content,
            source_type=self._source_type_for(stage, metadata),
            trace_id=str(payload.get("trace_id") or uuid4()),
            session_id=str(payload.get("session_id") or ""),
            user_id=str(payload.get("user_id") or ""),
            role_level=int(payload.get("role_level", 0)),
            principal_type=str(
                payload.get("principal_type") or "external_user"
            ),
            target_audience=str(
                payload.get("target_audience") or "external"
            ),
            channel_classification=str(
                payload.get("channel_classification") or "public"
            ),
            purpose=str(payload.get("purpose") or ""),
            allowed_data_scopes=set(allowed_scopes),
            metadata=metadata,
            parent_event_id=(
                str(payload["parent_event_id"])
                if payload.get("parent_event_id")
                else None
            ),
        )

        if stage == "input":
            result = self.guard.pre_check(request)
        elif stage == "context":
            result = self.guard.check_retrieval_content(request)
        else:
            result = self.guard.post_check(request)
        response = result.to_dict()
        event_builder = self.guard.audit_logger or AuditLogger()
        response["event"] = event_builder.build_event(stage, request, result)
        return response


def build_service(
    policy_path: Path | str,
    audit_path: Path | str | None,
) -> GuardService:
    logger = AuditLogger(audit_path) if audit_path else None
    return GuardService(
        IOGuard.from_policy_file(policy_path, audit_logger=logger)
    )


def create_handler(
    service: GuardService,
    *,
    api_token: str = "",
    max_body_bytes: int = 1_048_576,
) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        server_version = "IOGuard/0.1"

        def do_GET(self) -> None:  # noqa: N802
            if self.path == "/health":
                self._send_json(
                    HTTPStatus.OK,
                    {
                        "status": "ok",
                        "service": "io-guard",
                        "version": "0.2.0",
                        "semantic_detector": (
                            service.guard.semantic_detector.status()
                        ),
                    },
                )
                return
            self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                self._send_json(
                    HTTPStatus.UNAUTHORIZED, {"error": "unauthorized"}
                )
                return
            stage = {
                "/v1/check/input": "input",
                "/v1/check/context": "context",
                "/v1/check/output": "output",
            }.get(self.path)
            if stage is None:
                self._send_json(HTTPStatus.NOT_FOUND, {"error": "not_found"})
                return

            try:
                content_length = int(self.headers.get("Content-Length", "0"))
                if content_length <= 0 or content_length > max_body_bytes:
                    raise ValueError("invalid or oversized request body")
                body = self.rfile.read(content_length)
                payload = json.loads(body.decode("utf-8"))
                if not isinstance(payload, dict):
                    raise ValueError("JSON body must be an object")
                result = service.check(stage, payload)
            except (ValueError, TypeError, json.JSONDecodeError) as exc:
                self._send_json(
                    HTTPStatus.BAD_REQUEST,
                    {"error": "invalid_request", "detail": str(exc)},
                )
                return
            self._send_json(HTTPStatus.OK, result)

        def log_message(self, format: str, *args: object) -> None:
            return

        def _authorized(self) -> bool:
            if not api_token:
                return True
            supplied = self.headers.get("Authorization", "")
            expected = f"Bearer {api_token}"
            return hmac.compare_digest(supplied, expected)

        def _send_json(
            self, status: HTTPStatus, payload: dict[str, Any]
        ) -> None:
            encoded = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(encoded)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(encoded)

    return Handler


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the local IO Guard service")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument(
        "--policy",
        default="configs/default_policy.json",
        type=Path,
    )
    parser.add_argument(
        "--audit",
        default="work/openclaw_audit.jsonl",
        type=Path,
    )
    parser.add_argument("--max-body-bytes", default=1_048_576, type=int)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    service = build_service(args.policy, args.audit)
    token = os.environ.get("IO_GUARD_API_TOKEN", "")
    handler = create_handler(
        service,
        api_token=token,
        max_body_bytes=args.max_body_bytes,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"IO Guard listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
