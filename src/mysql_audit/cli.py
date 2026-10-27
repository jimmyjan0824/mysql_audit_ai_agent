"""Command line: mysql-audit migration.sql [--schema schema.sql] [--format json]

Exit code: 0 safe, 1 review, 2 block.
"""

from __future__ import annotations

import argparse
import json
import sys

from .engine import review

_EXIT = {"safe": 0, "review": 1, "block": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mysql-audit", description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="SQL files to review (stdin when omitted)")
    parser.add_argument("--schema", help="file with CREATE TABLE statements for the current schema")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    schema = open(args.schema, encoding="utf-8").read() if args.schema else None
    sources = [(f, open(f, encoding="utf-8").read()) for f in args.files] or [("<stdin>", sys.stdin.read())]

    worst = 0
    results = []
    for name, sql in sources:
        report = review(sql, schema=schema)
        worst = max(worst, _EXIT[report.verdict])
        results.append({"file": name, **report.to_dict()})

    if args.format == "json":
        print(json.dumps(results if len(results) > 1 else results[0], indent=2, ensure_ascii=False))
    else:
        for r in results:
            print(f"{r['file']}: {r['verdict'].upper()} ({r['statements']} statements)")
            for f in r["findings"]:
                print(f"  line {f['line']} [{f['severity']}] {f['rule_id']}: {f['message']}")
                print(f"    fix: {f['fix']}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
