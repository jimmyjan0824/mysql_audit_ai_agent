"""Data types shared by the engine, the rules and the front ends (CLI, MCP)."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Severity(str, Enum):
    """How an agent should treat a finding.

    block: do not run the statement as written.
    warn:  run only after a human or the agent has checked the risk.
    info:  worth knowing, no action required.
    """

    BLOCK = "block"
    WARN = "warn"
    INFO = "info"


@dataclass
class Finding:
    rule_id: str
    severity: Severity
    line: int
    statement: str
    message: str
    impact: str
    fix: str

    def to_dict(self) -> dict:
        return {
            "rule_id": self.rule_id,
            "severity": self.severity.value,
            "line": self.line,
            "statement": self.statement,
            "message": self.message,
            "impact": self.impact,
            "fix": self.fix,
        }


@dataclass
class Report:
    findings: list[Finding] = field(default_factory=list)
    statements: int = 0
    notes: list[str] = field(default_factory=list)

    @property
    def verdict(self) -> str:
        """safe / review / block, the one word an agent can branch on."""
        severities = {f.severity for f in self.findings}
        if Severity.BLOCK in severities:
            return "block"
        if Severity.WARN in severities:
            return "review"
        return "safe"

    def to_dict(self) -> dict:
        return {
            "verdict": self.verdict,
            "statements": self.statements,
            "findings": [f.to_dict() for f in self.findings],
            "notes": self.notes,
        }
