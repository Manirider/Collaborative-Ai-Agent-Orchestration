import logging
import json
import os
import re
from datetime import datetime, timezone

SENSITIVE_PATTERN = re.compile(
    r'(password|secret|key|token|auth|credential)["\']?\s*[:=]\s*["\']?([^"\',\s]+)',
    re.IGNORECASE,
)


def redact_sensitive(text: str) -> str:
    """Redact passwords, API keys, and sensitive tokens from log messages."""
    return SENSITIVE_PATTERN.sub(r'\1=[REDACTED]', str(text))


class JsonLineFormatter(logging.Formatter):
    def format(self, record):
        message = record.getMessage()
        log_obj = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "message": redact_sensitive(message),
        }
        # Add extra fields if present
        for key in ("task_id", "agent_name", "action_details"):
            if hasattr(record, key):
                val = getattr(record, key)
                log_obj[key] = redact_sensitive(val) if isinstance(val, str) else val
        return json.dumps(log_obj)


def setup_logging(log_file: str, level: str = "INFO"):
    dir_name = os.path.dirname(log_file)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)
    logger = logging.getLogger()
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

    if logger.handlers:
        return logger

    try:
        file_handler = logging.FileHandler(log_file, encoding="utf-8")
        file_handler.setFormatter(JsonLineFormatter())
        logger.addHandler(file_handler)
    except Exception as exc:
        # Fall back to console if file handler cannot be opened
        logging.warning("Failed to create file handler for %s: %s", log_file, exc)

    console_handler = logging.StreamHandler()
    console_formatter = logging.Formatter("%(levelname)s %(message)s")
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger


def log_agent_activity(task_id: str, agent_name: str, action_details: str, level=logging.INFO):
    logger = logging.getLogger()
    sanitized_action = redact_sensitive(action_details)
    logger.log(
        level,
        sanitized_action,
        extra={
            "task_id": str(task_id),
            "agent_name": str(agent_name),
            "action_details": sanitized_action,
        },
    )
