import re

from app.config import settings

REDACTION_VERSION = "v2"

REDACTION_PATTERNS = (
    (re.compile(r"AIza[A-Za-z0-9_-]{20,}"), "[REDACTED_API_KEY]"),
    (re.compile(r"(?i)(?:gemini_api_key|google_api_key|x-goog-api-key)\s*[:=]\s*[^\s\"']+"), "GEMINI_API_KEY=[REDACTED_API_KEY]"),
    (re.compile(r"sk-[A-Za-z0-9_-]{12,}"), "[REDACTED_API_KEY]"),
    (
        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}(?![A-Za-z0-9.-])"),
        "[REDACTED_EMAIL]",
    ),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}\b"), "[REDACTED_IP]"),
    (re.compile(r"(?i)bearer\s+[A-Za-z0-9._~+/-]+=*"), "Bearer [REDACTED_TOKEN]"),
)


def mask_sensitive_text(text: str) -> str:
    masked = text
    for secret in (settings.openai_api_key, settings.gemini_api_key):
        if secret:
            masked = masked.replace(secret, "[REDACTED_API_KEY]")
    for pattern, replacement in REDACTION_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked


def mask_sensitive_data(value):
    """Sanitize nested response/trace payloads as well as document metadata."""
    if isinstance(value, str):
        return mask_sensitive_text(value)
    if isinstance(value, dict):
        return {key: mask_sensitive_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_sensitive_data(item) for item in value]
    return value
