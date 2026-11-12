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


# Personal data in user stories. Applied to the story only: statute and guide text carry hotline
# numbers that must survive. Order matters: phone numbers also look like hyphenated account numbers.
_NOT_DIGIT_BEFORE, _NOT_DIGIT_AFTER = r"(?<!\d)", r"(?!\d)"
STORY_PATTERNS = (
    (re.compile(_NOT_DIGIT_BEFORE + r"\d{2}(?:0[1-9]|1[0-2])(?:0[1-9]|[12]\d|3[01])[- ]?[1-8]\d{6}" + _NOT_DIGIT_AFTER), "[주민번호]"),
    (re.compile(_NOT_DIGIT_BEFORE + r"01[016789][-. ]?\d{3,4}[-. ]?\d{4}" + _NOT_DIGIT_AFTER), "[전화번호]"),
    (re.compile(_NOT_DIGIT_BEFORE + r"0\d{1,2}[-. ]\d{3,4}[-. ]\d{4}" + _NOT_DIGIT_AFTER), "[전화번호]"),
    (re.compile(_NOT_DIGIT_BEFORE + r"\d{2,6}(?:-\d{2,8}){2,3}" + _NOT_DIGIT_AFTER), "[계좌번호]"),
    (re.compile(_NOT_DIGIT_BEFORE + r"\d{10,16}" + _NOT_DIGIT_AFTER), "[계좌번호]"),
)
# shortcut: names are only caught when written as "이름은 OOO" or "OOO 씨/님"; a NER model would catch more.
# "이름이" is left out: "닉네임 이름이 바뀌었어요" is common. The match may swallow a particle ("[이름]요").
_NAMED = re.compile(r"((?:이름|실명)(?:은|는|\s*:)\s*)[가-힣]{2,3}")
_HONORIFIC = re.compile(r"(?<![가-힣])([가-힣]{2,4})(?=\s?(?:씨|님)(?:[이가은는을를의에도만과와랑]|께서|한테|에게|$|[^가-힣]))")
NOT_NAMES = {
    "아저", "아가", "선생", "고객", "운영자", "관리자", "판매자", "구매자", "사장", "회원", "유저", "엄마", "아빠",
    "부모", "어머", "아버", "할머", "할아버", "친구", "상대", "상대방", "길드장", "방장", "형", "누나", "언니", "오빠",
    "교수", "기사", "작가", "경찰관", "수사관", "판사", "검사", "변호사", "선배", "후배", "팀장", "부장", "과장",
}


def mask_story(text: str) -> str:
    masked = mask_sensitive_text(text)
    for pattern, replacement in STORY_PATTERNS:
        masked = pattern.sub(replacement, masked)
    masked = _NAMED.sub(lambda match: f"{match.group(1)}[이름]", masked)
    return _HONORIFIC.sub(lambda match: match.group(1) if match.group(1) in NOT_NAMES else "[이름]", masked)


def mask_sensitive_data(value):
    """Sanitize nested response/trace payloads as well as document metadata."""
    if isinstance(value, str):
        return mask_sensitive_text(value)
    if isinstance(value, dict):
        return {key: mask_sensitive_data(item) for key, item in value.items()}
    if isinstance(value, list):
        return [mask_sensitive_data(item) for item in value]
    return value
