import re


REDACTION_PATTERNS = (
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
    for pattern, replacement in REDACTION_PATTERNS:
        masked = pattern.sub(replacement, masked)
    return masked
