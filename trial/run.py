"""Run every trial example and compare the result with what the file expects.

    python trial/run.py            # summary table
    python trial/run.py -v         # also print every finding
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

from mysql_audit import review, review_code

HERE = Path(__file__).parent


def expected(text: str) -> str:
    m = re.search(r"^(?:--|#) expect: (\w+)", text, re.MULTILINE)
    return m.group(1) if m else "?"


def main() -> int:
    verbose = "-v" in sys.argv
    schema = (HERE / "schema.sql").read_text(encoding="utf-8")
    stats = json.loads((HERE / "stats.json").read_text(encoding="utf-8"))
    files = sorted((HERE / "migrations").glob("*.sql")) + sorted((HERE / "code").glob("*.py"))
    mismatches = 0
    print(f"{'file':42} {'expect':7} {'result':7} rules")
    for path in files:
        text = path.read_text(encoding="utf-8")
        report = review_code(text) if path.suffix == ".py" else review(text, schema=schema, stats=stats)
        want = expected(text)
        rules = sorted({f.rule_id for f in report.findings if f.severity.value != "info"})
        mark = "" if report.verdict == want else "  <-- differs"
        mismatches += bool(mark)
        print(f"{path.parent.name + '/' + path.name:42} {want:7} {report.verdict:7} {' '.join(rules)}{mark}")
        if verbose:
            for f in report.findings:
                print(f"    line {f.line} [{f.severity.value}] {f.rule_id}: {f.message}")
    print(f"\n{len(files)} examples, {mismatches} differ from the expected result.")
    return 1 if mismatches else 0


if __name__ == "__main__":
    sys.exit(main())
