from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Severity

DDL_KINDS = {"alter_table", "create_index", "drop_index", "drop_table", "rename_table", "truncate"}


@dataclass(frozen=True)
class Rule:
    id: str
    title: str
    severity: Severity  # the usual severity; a check may raise or lower it
    why: str
    safe_example: str
    check: Callable[[Analyzed, ScriptContext], list[Finding]]

    def explain(self) -> dict:
        return {
            "rule_id": self.id,
            "title": self.title,
            "default_severity": self.severity.value,
            "why": self.why,
            "safe_example": self.safe_example,
        }


def excerpt(a: Analyzed, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", a.stmt.sql).strip()
    return text if len(text) <= limit else text[: limit - 3] + "..."


def finding(rule_id: str, severity: Severity, a: Analyzed, message: str, impact: str, fix: str) -> Finding:
    return Finding(rule_id, severity, a.stmt.line, excerpt(a), message, impact, fix)
