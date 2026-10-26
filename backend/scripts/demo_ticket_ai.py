"""Exercise existing ticket HTTP routes using an isolated, disposable SQLite file."""

import argparse
import json
import logging
import os
import re
import secrets
import sys
import warnings
from collections.abc import Generator, Mapping
from contextlib import ExitStack
from pathlib import Path
from sqlite3 import Connection
from tempfile import TemporaryDirectory
from threading import Lock
from typing import Any
from unittest.mock import patch

import httpx

MOCK_ANALYSIS = {
    "category": "billing",
    "summary": "用户反馈会员支付成功但权益未开通，实际状态待核查。",
    "suggested_priority": "medium",
    "suggested_reply": "您反馈已支付但会员权益尚未开通。目前无法确认支付状态和权益状态；建议提供订单号，由具备查询权限的客服核查。",
}


class DemoError(Exception):
    """Fixed, non-sensitive error codes only."""


def mock_completion() -> dict[str, Any]:
    return {
        "id": "demo-mock-response",
        "object": "chat.completion",
        "created": 1,
        "model": "demo-mock",
        "choices": [
            {
                "index": 0,
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": json.dumps(MOCK_ANALYSIS, ensure_ascii=False),
                },
            }
        ],
    }


class SingleCallTransport(httpx.BaseTransport):
    def __init__(self, delegate: httpx.BaseTransport) -> None:
        self.delegate = delegate
        self.calls = 0
        self.prompt_policy_present = False
        self._lock = Lock()

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        with self._lock:
            if self.calls >= 1:
                raise DemoError("ai_attempt_limit")
            self.calls += 1
        if request.content:
            body = json.loads(request.content)
            messages = body.get("messages", [])
            system = messages[0].get("content", "") if messages else ""
            self.prompt_policy_present = all(
                text in system
                for text in (
                    "用户陈述不等于已核实事实",
                    "不得编造处理进度",
                    "不得作出时间承诺",
                )
            )
        return self.delegate.handle_request(request)

    def close(self) -> None:
        self.delegate.close()


def quality_flags(analysis: Mapping[str, str]) -> list[dict[str, str]]:
    """Conservative Chinese phrase checks, not a factuality or semantic verifier."""
    rules = {
        "unverified_fact": r"(?:已(?:经)?)(?:核实|核对|确认|查实|查到|查询到)",
        "completed_action_or_progress": r"(?:已(?:经)?(?:为您|为你)?(?:完成|退款|开通|激活|恢复|受理|转人工|转交|提交|安排|催办)|正在(?:为您)?处理)",
        "time_promise": r"(?:(?:\d+|[一二三四五六七八九十两]+)\s*(?:分钟|小时|天|工作日)(?:内|后)?|稍后|马上|立即|很快|尽快)[^。！？\n]{0,10}(?:生效|恢复|开通|到账|解决)",
        "operation_promise": r"(?:保证|确保|承诺|会|将)(?:为您|为你)?[^。！？\n]{0,8}(?:人工开通|开通会员|开通权益|退款到账|解决)",
        "unattributed_payment_fact": r"(?:您的|你的)?(?:支付|付款|交易)(?:已(?:经)?)?(?:成功|到账)",
    }
    negatives = (
        "不",
        "不能",
        "不会",
        "无法",
        "不应",
        "不得",
        "不保证",
        "无法承诺",
        "不能保证",
        "不承诺",
    )
    flags: list[dict[str, str]] = []
    for field in ("summary", "suggested_reply"):
        text = analysis.get(field, "")
        for reason, pattern in rules.items():
            for match in re.finditer(pattern, text):
                prefix = re.split(r"[。！？\n]", text[: match.start()])[-1].rstrip()
                if prefix.endswith(negatives):
                    continue
                if reason == "unattributed_payment_fact" and re.search(
                    r"用户反馈|您反馈|据您描述|您提到|根据您提供", prefix
                ):
                    continue
                flags.append({"field": field, "reason": reason})
                break
    return flags


def _redact(value: Any, jwt: str, api_key: str = "") -> Any:
    if isinstance(value, dict):
        return {key: _redact(item, jwt, api_key) for key, item in value.items()}
    if isinstance(value, list):
        return [_redact(item, jwt, api_key) for item in value]
    if isinstance(value, str):
        if jwt:
            value = value.replace(jwt, "[REDACTED_JWT]")
        if api_key:
            value = value.replace(api_key, "[REDACTED_KEY]")
        value = re.sub(r"\beyJ[\w-]+\.[\w-]+\.[\w-]+", "[REDACTED_JWT]", value)
        return re.sub(r"\bsk-[A-Za-z0-9_-]+", "[REDACTED_KEY]", value)
    return value


def _json_response(
    response: httpx.Response, expected: int, step: str
) -> dict[str, Any]:
    if response.status_code != expected:
        raise DemoError(f"{step}_http_error")
    payload = response.json()
    if not isinstance(payload, dict):
        raise DemoError(f"{step}_invalid_response")
    return payload


def run_demo(*, real_ai: bool = False) -> tuple[dict[str, Any], int]:
    report: dict[str, Any] = {
        "mode": "real" if real_ai else "mock",
        "database": "isolated_temporary_sqlite_file",
        "http_flow": [],
        "ai_analysis": None,
        "pydantic_validation": "not_run",
        "quality": {"status": "not_run", "flags": [], "requires_human_review": True},
        "checks": {},
        "request_sessions": 0,
    }
    token = ""
    active_api_key = ""
    database_path: Path | None = None
    transport: SingleCallTransport | None = None
    previous_logging = logging.root.manager.disable
    logging.disable(logging.CRITICAL)
    code = 1
    try:
        with ExitStack() as stack:
            stack.enter_context(warnings.catch_warnings())
            warnings.simplefilter("ignore")
            # Process-local configuration; never load a real application DB connection.
            stack.enter_context(
                patch.dict(
                    os.environ,
                    {
                        "DATABASE_URL": "postgresql+psycopg://demo:demo@127.0.0.1:1/blocked",
                        "SECRET_KEY": secrets.token_urlsafe(32),
                        "PROJECT_NAME": "Isolated ticket demonstration",
                        "FIRST_SUPERUSER": "demo-admin@example.com",
                        "FIRST_SUPERUSER_PASSWORD": secrets.token_urlsafe(24),
                        "FASTAPI_ENV": "development",
                    },
                )
            )
            from fastapi.testclient import TestClient
            from openai import OpenAI
            from pydantic import SecretStr
            from sqlalchemy import event
            from sqlalchemy.pool import NullPool
            from sqlmodel import Session, SQLModel, create_engine

            from app.api.deps import get_db
            from app.core.config import settings
            from app.core.db import engine as application_engine
            from app.core.security import get_password_hash
            from app.main import app
            from app.models import Ticket, TicketPublic, User
            from app.services import ticket_ai

            def forbid_application_db(*_args: object, **_kwargs: object) -> None:
                raise DemoError("application_database_access_blocked")

            for name in ("do_connect", "checkout"):
                event.listen(application_engine, name, forbid_application_db)
                stack.callback(
                    event.remove, application_engine, name, forbid_application_db
                )

            directory = stack.enter_context(TemporaryDirectory())
            database_path = Path(directory) / "tickets.sqlite3"
            engine = create_engine(
                f"sqlite:///{database_path.as_posix()}",
                connect_args={"check_same_thread": False},
                poolclass=NullPool,
            )
            stack.callback(engine.dispose)

            @event.listens_for(engine, "connect")
            def enable_foreign_keys(connection: Connection, _record: object) -> None:
                connection.execute("PRAGMA foreign_keys=ON")

            SQLModel.metadata.create_all(engine)
            email = "demo-customer@example.com"
            password = secrets.token_urlsafe(24)
            with Session(engine) as seed:
                seed.add(User(email=email, hashed_password=get_password_hash(password)))
                seed.commit()

            def override_db() -> Generator[Session]:
                report["request_sessions"] += 1
                with Session(engine) as session:
                    yield session

            stack.enter_context(
                patch.dict(app.dependency_overrides, {get_db: override_db}, clear=True)
            )
            if not real_ai:
                stack.enter_context(
                    patch.object(
                        settings, "DASHSCOPE_API_KEY", SecretStr("demo-only-key")
                    )
                )
            delegate = (
                httpx.HTTPTransport(retries=0)
                if real_ai
                else httpx.MockTransport(
                    lambda _request: httpx.Response(200, json=mock_completion())
                )
            )
            transport = SingleCallTransport(delegate)
            stack.callback(transport.close)

            def sdk_client(**kwargs: Any) -> OpenAI:
                nonlocal active_api_key
                # Reuse only the credential already supplied for SDK authentication.
                # Keep it in memory for exact output redaction, never in the report.
                candidate_key = kwargs.get("api_key")
                active_api_key = candidate_key if isinstance(candidate_key, str) else ""
                kwargs["http_client"] = httpx.Client(
                    transport=transport, follow_redirects=False
                )
                kwargs["max_retries"] = 0
                return OpenAI(**kwargs)

            stack.enter_context(patch.object(ticket_ai, "OpenAI", sdk_client))
            api = settings.API_V1_STR

            def step(
                name: str, method: str, path: str, response: httpx.Response
            ) -> None:
                report["http_flow"].append(
                    {
                        "step": name,
                        "method": method,
                        "path": path,
                        "status": response.status_code,
                    }
                )

            with TestClient(app, raise_server_exceptions=False) as client:
                response = client.post(
                    f"{api}/login/access-token",
                    data={"username": email, "password": password},
                )
                step("login", "POST", f"{api}/login/access-token", response)
                login = _json_response(response, 200, "login")
                candidate = login.get("access_token")
                if not isinstance(candidate, str) or not candidate:
                    raise DemoError("login_invalid_response")
                token = candidate
                headers = {"Authorization": f"Bearer {token}"}
                response = client.post(
                    f"{api}/tickets/",
                    headers=headers,
                    json={
                        "title": "会员支付成功，但账户权益没有开通",
                        "description": "虚构演示：用户反馈已支付会员费用，但账户权益尚未开通；实际支付和权益状态待核查。",
                        "priority": "medium",
                    },
                )
                step("create_ticket", "POST", f"{api}/tickets/", response)
                created = _json_response(response, 201, "create_ticket")
                ticket_id = TicketPublic.model_validate(created).id
                url = f"{api}/tickets/{ticket_id}"
                response = client.get(url, headers=headers)
                step("read_ticket", "GET", f"{api}/tickets/{{ticket_id}}", response)
                before = _json_response(response, 200, "read_ticket")
                if before != created:
                    raise DemoError("created_ticket_not_persisted")
                report["ticket"] = {
                    key: before[key]
                    for key in ("title", "description", "status", "priority")
                }
                response = client.post(f"{url}/ai-analysis", headers=headers)
                step(
                    "ai_analysis",
                    "POST",
                    f"{api}/tickets/{{ticket_id}}/ai-analysis",
                    response,
                )
                errors: list[str] = []
                if response.status_code == 200:
                    analysis = ticket_ai.TicketAIAnalysis.model_validate_json(
                        response.content
                    )
                    report["ai_analysis"] = analysis.model_dump(mode="json")
                    report["pydantic_validation"] = "passed"
                    flags = quality_flags(report["ai_analysis"])
                    report["quality"] = {
                        "status": "failed" if flags else "no_flags",
                        "flags": flags,
                        "requires_human_review": True,
                    }
                else:
                    errors.append("ai_http_error")
                response = client.get(url, headers=headers)
                step(
                    "read_after_analysis",
                    "GET",
                    f"{api}/tickets/{{ticket_id}}",
                    response,
                )
                after = _json_response(response, 200, "read_after_analysis")
                with Session(engine) as observer:
                    stored = observer.get(Ticket, ticket_id)
                    persisted = (
                        TicketPublic.model_validate(stored).model_dump(mode="json")
                        if stored
                        else None
                    )
                report["checks"] = {
                    "http_ticket_unchanged": before == after,
                    "new_connection_ticket_unchanged": before == persisted,
                    "fields_checked": sorted(before),
                }
                if before != after or before != persisted:
                    errors.append("ticket_was_modified")
                if transport.calls and not transport.prompt_policy_present:
                    errors.append("prompt_policy_not_detected")
                report["prompt_policy_present"] = transport.prompt_policy_present
                report["errors"] = errors
                code = (
                    1 if errors else 2 if report["quality"]["status"] == "failed" else 0
                )
                report["result"] = (
                    "failed"
                    if code == 1
                    else "quality_failed"
                    if code == 2
                    else "passed"
                )
    except DemoError as error:
        report.update(result="failed", error=str(error))
        code = 1
    except Exception:
        # No raw traceback, HTTP body, headers, environment values or provider message.
        report.update(result="failed", error="unexpected_demo_error")
        code = 1
    finally:
        logging.disable(previous_logging)
    calls = transport.calls if transport else 0
    report["ai_attempts"] = {
        "mock": 0 if real_ai else calls,
        "real": calls if real_ai else 0,
        "limit": 1,
    }
    report["database_removed"] = (
        database_path is not None and not database_path.exists()
    )
    return _redact(report, token, active_api_key), code


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--real-ai",
        action="store_true",
        help="Explicitly allow at most one real Qwen HTTP attempt; may incur cost.",
    )
    args = parser.parse_args()
    report, code = run_demo(real_ai=args.real_ai)
    sys.stdout.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    return code


if __name__ == "__main__":
    raise SystemExit(main())
