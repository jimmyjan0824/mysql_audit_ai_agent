"""Command line: mysql-audit migration.sql [--schema schema.sql] [--stats rows.json] [--mysql-version 8.0.28] [--free-disk-gb 120]

Settings left out are read from .mysql-audit.toml in the current directory or
a parent. Exit code: 0 safe, 1 review, 2 block.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .config import load_config, parse_gb
from .engine import review, review_code
from .version import parse_version

_EXIT = {"safe": 0, "review": 1, "block": 2}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mysql-audit", description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="SQL files to review (stdin when omitted)")
    parser.add_argument("--schema", help="file with CREATE TABLE statements for the current schema")
    parser.add_argument("--stats", help='JSON file of table sizes: {"orders": 25000000} or {"orders": {"rows": ..., "data_bytes": ..., "index_bytes": ...}}')
    parser.add_argument("--code", action="store_true", help="files are application code: check for SQL injection")
    parser.add_argument("--mysql-version", help="target server, e.g. 8.0.28, 8.4.3 or aurora-3.04 (default: 8.0.29 or later)")
    parser.add_argument("--free-disk-gb", help="free space on the server's data volume, in GB (enables L17)")
    parser.add_argument("--config", help="settings file (default: the nearest .mysql-audit.toml)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    args = parser.parse_args(argv)

    try:
        cfg = load_config(path=Path(args.config) if args.config else None)
        version = args.mysql_version or cfg.mysql_version
        if version:
            parse_version(version)
        free_disk = parse_gb(args.free_disk_gb) if args.free_disk_gb else cfg.free_disk_gb
    except (OSError, ValueError) as e:
        parser.error(str(e))
    schema = open(args.schema, encoding="utf-8").read() if args.schema else cfg.schema
    stats = json.load(open(args.stats, encoding="utf-8")) if args.stats else cfg.stats
    sources = [(f, open(f, encoding="utf-8").read()) for f in args.files] or [("<stdin>", sys.stdin.read())]

    worst = 0
    results = []
    for name, sql in sources:
        report = review_code(sql) if args.code else review(sql, schema=schema, stats=stats, mysql_version=version, free_disk_gb=free_disk)
        worst = max(worst, _EXIT[report.verdict])
        results.append({"file": name, **report.to_dict()})

    if args.format == "json":
        print(json.dumps(results if len(results) > 1 else results[0], indent=2, ensure_ascii=False))
    else:
        for r in results:
            counted = "" if args.code else f" ({r['statements']} statements)"
            print(f"{r['file']}: {r['verdict'].upper()}{counted}")
            for f in r["findings"]:
                print(f"  line {f['line']} [{f['severity']}] {f['rule_id']}: {f['message']}")
                print(f"    fix: {f['fix']}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
