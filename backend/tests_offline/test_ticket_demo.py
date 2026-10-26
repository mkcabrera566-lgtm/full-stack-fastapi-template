import importlib.util
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from tempfile import TemporaryDirectory
from types import ModuleType
from unittest.mock import MagicMock

import httpx
import pytest
from pydantic import SecretStr

DEMO_PATH = Path(__file__).parents[1] / "scripts" / "demo_ticket_ai.py"


@pytest.fixture
def demo(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> ModuleType:
    spec = importlib.util.spec_from_file_location("ticket_demo", DEMO_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(
        module, "TemporaryDirectory", lambda: TemporaryDirectory(dir=tmp_path)
    )
    return module


def test_default_cli_runs_complete_mock_http_flow_without_credentials() -> None:
    env = os.environ.copy()
    fake_key = "do-not-log-this-demo-key"
    env["DASHSCOPE_API_KEY"] = fake_key
    result = subprocess.run(
        [sys.executable, "-X", "utf8", str(DEMO_PATH)],
        cwd=DEMO_PATH.parents[1],
        env=env,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=45,
    )
    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout)
    assert output["mode"] == "mock"
    assert [step["status"] for step in output["http_flow"]] == [200, 201, 200, 200, 200]
    assert set(output["ai_analysis"]) == {
        "category",
        "summary",
        "suggested_priority",
        "suggested_reply",
    }
    assert output["pydantic_validation"] == "passed"
    assert output["quality"]["status"] == "no_flags"
    assert output["checks"]["http_ticket_unchanged"] is True
    assert output["checks"]["new_connection_ticket_unchanged"] is True
    assert output["request_sessions"] == 5
    assert output["ai_attempts"] == {"mock": 1, "real": 0, "limit": 1}
    assert output["database_removed"] is True
    assert fake_key not in result.stdout + result.stderr
    assert "access_token" not in result.stdout
    assert "Authorization" not in result.stdout
    assert not re.search(r"eyJ[\w-]+\.[\w-]+\.[\w-]+", result.stdout)


def test_demo_isolated_database_and_overrides_are_cleaned_up(
    demo: ModuleType, tmp_path: Path
) -> None:
    from app.main import app

    sentinel = tmp_path / "existing.sqlite3"
    sentinel.write_bytes(b"existing database must stay unchanged")
    previous = app.dependency_overrides.copy()
    output, code = demo.run_demo()
    assert code == 0
    assert output["database_removed"] is True
    assert sentinel.read_bytes() == b"existing database must stay unchanged"
    assert list(tmp_path.iterdir()) == [sentinel]
    assert app.dependency_overrides == previous


@pytest.mark.parametrize(
    "reply",
    [
        "我们已核实您的支付记录，权益5分钟内生效，我们会人工开通。",
        "已为您退款到账，工单已转人工，正在处理，稍后自动恢复。",
        "您的支付已成功，保证为您开通会员。",
    ],
)
def test_mock_quality_failure_is_recorded_without_changing_ticket(
    demo: ModuleType, monkeypatch: pytest.MonkeyPatch, reply: str
) -> None:
    monkeypatch.setitem(demo.MOCK_ANALYSIS, "suggested_reply", reply)
    output, code = demo.run_demo()
    assert code == 2
    assert output["result"] == "quality_failed"
    assert output["quality"]["status"] == "failed"
    assert output["quality"]["flags"]
    assert output["checks"]["new_connection_ticket_unchanged"] is True
    assert output["ai_attempts"]["real"] == 0


@pytest.mark.parametrize(
    "reply",
    [
        "您反馈已支付，但目前无法确认支付状态和权益状态，建议提供订单号供客服核查。",
        "尚未核实订单，无法承诺5分钟生效，不能保证人工开通。",
    ],
)
def test_neutral_reply_has_no_heuristic_flags(demo: ModuleType, reply: str) -> None:
    assert (
        demo.quality_flags(
            {
                "summary": "用户反馈会员权益未开通，状态待核查。",
                "suggested_reply": reply,
            }
        )
        == []
    )


def test_real_mode_is_explicit_and_guarded_without_real_network(
    demo: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", SecretStr("unit-test-key"))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json=demo.mock_completion())

    monkeypatch.setattr(
        httpx, "HTTPTransport", lambda **_kwargs: httpx.MockTransport(handler)
    )
    output, code = demo.run_demo(real_ai=True)
    assert code == 0
    assert output["mode"] == "real"
    assert calls == ["POST"]
    assert output["ai_attempts"] == {"mock": 0, "real": 1, "limit": 1}


def test_transport_blocks_second_attempt(demo: ModuleType) -> None:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(200, json={})

    transport = demo.SingleCallTransport(httpx.MockTransport(handler))
    request = httpx.Request("POST", "https://demo.example.test/chat/completions")
    with transport:
        transport.handle_request(request)
        with pytest.raises(demo.DemoError, match="ai_attempt_limit"):
            transport.handle_request(request)
    assert calls == ["POST"]
    assert transport.calls == 1


def test_real_mode_missing_key_does_not_attempt_network(
    demo: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", None)
    factory = MagicMock(side_effect=AssertionError("must not open transport"))
    # Transport construction is local; its request handler must remain unused.
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", factory)
    output, code = demo.run_demo(real_ai=True)
    assert code == 1
    assert output["http_flow"][3]["status"] == 503
    assert output["ai_attempts"]["real"] == 0
    assert output["checks"]["new_connection_ticket_unchanged"] is True
    factory.assert_not_called()


def test_real_mode_does_not_follow_redirects(
    demo: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", SecretStr("unit-test-key"))
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.method)
        return httpx.Response(
            307, headers={"Location": "https://redirect.example.test/"}
        )

    monkeypatch.setattr(
        httpx, "HTTPTransport", lambda **_kwargs: httpx.MockTransport(handler)
    )
    output, code = demo.run_demo(real_ai=True)
    assert code == 1
    assert calls == ["POST"]
    assert output["ai_attempts"]["real"] == 1
    assert output["checks"]["new_connection_ticket_unchanged"] is True


def test_demo_output_redacts_tokens_and_key_patterns(demo: ModuleType) -> None:
    output = demo._redact(
        {
            "ai_analysis": {
                "suggested_reply": "private-token sk-demo-secret eyJdemo.eyJdemo.signature"
            }
        },
        "private-token",
    )
    rendered = json.dumps(output)
    assert "private-token" not in rendered
    assert "sk-demo-secret" not in rendered
    assert "eyJdemo" not in rendered
    assert "[REDACTED_JWT]" in rendered
    assert "[REDACTED_KEY]" in rendered


def test_echoed_nonstandard_api_key_is_redacted_without_real_network(
    demo: ModuleType, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.core.config import settings

    dummy_key = "arbitrary-demo-credential"
    monkeypatch.setattr(settings, "DASHSCOPE_API_KEY", SecretStr(dummy_key))
    monkeypatch.setitem(demo.MOCK_ANALYSIS, "suggested_reply", dummy_key)
    monkeypatch.setattr(
        httpx,
        "HTTPTransport",
        lambda **_kwargs: httpx.MockTransport(
            lambda _request: httpx.Response(200, json=demo.mock_completion())
        ),
    )
    output, code = demo.run_demo(real_ai=True)
    assert code == 0
    assert dummy_key not in json.dumps(output)
    assert output["ai_analysis"]["suggested_reply"] == "[REDACTED_KEY]"
