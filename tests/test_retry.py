import json
import logging
import uuid
import pytest

from src.agents.tools import research_tool, TransientError
from src.observability.logging_config import JsonLineFormatter, redact_sensitive, log_agent_activity


def test_flaky_tool_fails_first_then_succeeds():
    """__FLAKY_TEST__ marker causes first invocation to fail with TransientError and second to succeed."""
    task_id = str(uuid.uuid4())
    flaky_prompt = "Compare tools __FLAKY_TEST__"

    # First attempt must fail with TransientError
    with pytest.raises(TransientError, match="Simulated transient network error"):
        research_tool(flaky_prompt, task_id)

    # Second attempt must succeed and return findings
    findings = research_tool(flaky_prompt, task_id)
    assert findings is not None
    assert "langgraph" in findings
    assert "crewai" in findings
    assert findings["prompt"] == flaky_prompt


def test_normal_tool_succeeds_immediately():
    """Prompts without flaky marker must succeed on the first invocation."""
    task_id = str(uuid.uuid4())
    findings = research_tool("Normal research query", task_id)
    assert findings is not None
    assert "langgraph" in findings
    assert "crewai" in findings


def test_sensitive_data_redaction():
    """Sensitive patterns (passwords, tokens, API keys) must be redacted from logs."""
    raw_message = "Connecting with password=supersecret and token=abc123xyz"
    sanitized = redact_sensitive(raw_message)
    assert "supersecret" not in sanitized
    assert "abc123xyz" not in sanitized
    assert "password=[REDACTED]" in sanitized
    assert "token=[REDACTED]" in sanitized


def test_json_lines_log_formatter():
    """Log records formatted by JsonLineFormatter must produce valid, parseable JSON."""
    formatter = JsonLineFormatter()
    record = logging.LogRecord(
        name="test_logger",
        level=logging.INFO,
        pathname=__file__,
        lineno=10,
        msg="Task execution verified with password=secret",
        args=(),
        exc_info=None,
    )
    record.task_id = "12345"
    record.agent_name = "TestAgent"
    record.action_details = "Testing auth token=secrettoken"

    formatted = formatter.format(record)
    parsed = json.loads(formatted)

    assert parsed["level"] == "INFO"
    assert parsed["task_id"] == "12345"
    assert parsed["agent_name"] == "TestAgent"
    assert "timestamp" in parsed
    # Sensitive data redacted
    assert "secret" not in parsed["message"]
    assert "secrettoken" not in parsed["action_details"]
