"""输出脱敏辅助函数。桥接层不再提供任意本机 shell 执行入口。"""
from __future__ import annotations

import re

ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[A-Za-z]")

SECRET_PATTERNS = [
    (re.compile(r"(gh[pousr]_[A-Za-z0-9]{20,})"), "***"),
    (re.compile(r"(github_pat_[A-Za-z0-9_]{20,})"), "***"),
    (re.compile(r"(sk-[A-Za-z0-9_-]{16,})"), "***"),
    (re.compile(r"(cli_[a-z0-9]{10,})"), "cli_***"),
    (re.compile(r"(?i)(app[_-]?secret\s*[=:]\s*)(\S+)"), r"\1***"),
    (re.compile(r"(?i)(authorization:\s*bearer\s+)(\S+)"), r"\1***"),
    (
        re.compile(
            r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
            re.S,
        ),
        "***",
    ),
]


def strip_ansi(text: str) -> str:
    return ANSI_RE.sub("", text)


def redact(text: str) -> str:
    for pattern, replacement in SECRET_PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def truncate(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    head = int(limit * 0.6)
    tail = limit - head
    return text[:head] + "\n…（输出已截断）…\n" + text[-tail:]
