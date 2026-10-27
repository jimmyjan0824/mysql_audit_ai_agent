"""The DBA trial kit (trial/) must keep giving the results its files promise."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from mysql_audit import review, review_code

TRIAL = Path(__file__).parent.parent / "trial"
SCHEMA = (TRIAL / "schema.sql").read_text()
STATS = json.loads((TRIAL / "stats.json").read_text())
FILES = sorted((TRIAL / "migrations").glob("*.sql")) + sorted((TRIAL / "code").glob("*.py"))


def _header(text: str, key: str) -> list[str]:
    m = re.search(rf"^(?:--|#) {key}: (.+)$", text, re.MULTILINE)
    return m.group(1).split() if m else []


@pytest.mark.parametrize("path", FILES, ids=lambda p: p.name)
def test_trial_file_matches_its_header(path):
    text = path.read_text()
    report = review_code(text) if path.suffix == ".py" else review(text, schema=SCHEMA, stats=STATS)
    assert [report.verdict] == _header(text, "expect")
    found = {f.rule_id for f in report.findings if f.severity.value != "info"}
    assert set(_header(text, "rules")) <= found
