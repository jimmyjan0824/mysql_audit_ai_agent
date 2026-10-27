"""L12: SQL built from strings in application code (SQL injection).

Works on source code, not SQL: Python, JavaScript / TypeScript, PHP, Go and
Java patterns. Placeholders with separate parameters are the safe form and are
not flagged, nor are tagged templates such as sql`...`.
"""

from __future__ import annotations

import re

from ..models import Finding, Report, Severity
from .base import Rule

_SQL = r"(?:\bSELECT\b[^\"'`]*\bFROM\b|\bINSERT\s+INTO\b|\bUPDATE\b\s+\S+\s+\bSET\b|\bDELETE\s+FROM\b|\bWHERE\b)"

# Body of a string literal opened by quote group 1: anything but that quote.
_BODY = r"(?:(?!\1).)*"

_PATTERNS = [
    ("Python f-string", re.compile(r"\b(?:[rR]?[fF]|[fF][rR])([\"'])(?=" + _BODY + _SQL + r")" + _BODY + r"\{[^}]+\}", re.I)),
    ("JavaScript template literal", re.compile(r"(?<![\w.$])`(?=[^`]*" + _SQL + r")[^`]*\$\{", re.I)),
    ("string concatenation", re.compile(r"([\"'])(?=" + _BODY + _SQL + r")" + _BODY + r"\1\s*(?:\+|\.(?!\w))\s*\$?[A-Za-z_(]", re.I)),
    ("% formatting", re.compile(r"([\"'])(?=" + _BODY + _SQL + r")" + _BODY + r"%[sdr]" + _BODY + r"\1\s*%\s*[\w(]", re.I)),
    (".format()", re.compile(r"([\"'])(?=" + _BODY + _SQL + r")" + _BODY + r"\{\w*\}" + _BODY + r"\1\.format\(", re.I)),
    ("printf-style formatting", re.compile(r"(?:Sprintf|String\.format|sprintf)\(\s*\"(?=[^\"]*" + _SQL + r")[^\"]*%[sv]", re.I)),
    ("PHP string interpolation", re.compile(r"\"(?=[^\"]*" + _SQL + r")[^\"]*\$[A-Za-z_{]", re.I)),
]


def review_code(code: str) -> Report:
    report = Report()
    for lineno, line in enumerate(code.splitlines(), start=1):
        stripped = line.strip()
        if stripped.startswith(("#", "//", "*", "/*", "--")):
            continue
        for label, pattern in _PATTERNS:
            if pattern.search(line):
                report.findings.append(Finding(
                    "L12", Severity.BLOCK, lineno, stripped[:200],
                    f"SQL is built with {label}; a value from outside can change the query.",
                    "SQL injection: an attacker can read or delete any data the database user can reach.",
                    "Pass values as parameters: cursor.execute(\"... WHERE id = %s\", (user_id,)) in Python, "
                    "db.query(\"... WHERE id = ?\", [id]) in Node, prepared statements in PHP / Go / Java. "
                    "Table or column names must come from a fixed allow-list, never from input.",
                ))
                break
    return report


L12 = Rule(
    id="L12",
    title="SQL built by string interpolation (SQL injection)",
    severity=Severity.BLOCK,
    why=(
        "Agents often build SQL with f-strings, template literals or concatenation because it "
        "reads naturally. Any value that reaches such a string from a request can rewrite the "
        "query. Placeholders keep data and SQL apart. Checked by review_code on source code."
    ),
    safe_example='cursor.execute("SELECT * FROM users WHERE email = %s", (email,))',
    check=lambda a, ctx: [],  # runs on source code through review_code, not on SQL
)
