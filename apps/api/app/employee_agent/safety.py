"""Conservative prompt-injection and immediate-escalation classification."""

import re

_INJECTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\s+(all\s+)?(previous|prior|system)\s+instructions?\b",
        r"\breveal\s+(the\s+)?(system|developer)\s+prompt\b",
        r"\b(show|print|return)\s+(your\s+)?(hidden|system)\s+instructions?\b",
        r"\b(api[_ -]?key|password|secret|access token)\b.*\b(expose|reveal|print|send)\b",
        r"\b(run|execute)\s+(arbitrary\s+)?(sql|shell|powershell|bash|command)\b",
        r"<\s*/?\s*(system|assistant|developer|tool)\s*>",
    )
)

_ESCALATION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\b(security incident|suspected breach|data breach|ransomware|malware)\b",
        r"\b(payroll|salary|payslip)\b",
        r"\b(financial posting|general ledger|journal posting)\b",
        r"\b(production (outage|down)|system-wide outage|major incident)\b",
        r"\b(multiple|many|all) (users|employees) (are )?(affected|impacted)\b",
        r"\b(privileged access|administrator access|admin rights)\b",
        r"\b(previous (fix|solution) failed|already tried)\b",
    )
)


def contains_prompt_injection(value: str) -> bool:
    normalized = " ".join(value.replace("\x00", " ").split())
    return any(pattern.search(normalized) for pattern in _INJECTION_PATTERNS)


def requires_immediate_escalation(value: str) -> bool:
    normalized = " ".join(value.split())
    return any(pattern.search(normalized) for pattern in _ESCALATION_PATTERNS)


def safe_context(messages: tuple[dict[str, str], ...]) -> tuple[dict[str, str], ...]:
    return tuple(
        message
        for message in messages
        if message.get("role") != "user"
        or not contains_prompt_injection(message.get("content", ""))
    )
