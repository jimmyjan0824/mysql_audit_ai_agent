"""Command line: mysql-audit migration.sql [--schema schema.sql] [--stats rows.json] [--mysql-version 8.0.28] [--free-disk-gb 120]

Settings left out are read from .mysql-audit.toml in the current directory or
a parent. Exit code: 0 safe, 1 review, 2 block.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import __version__
from .config import load_config, parse_gb
from .engine import review, review_code
from .preflight import preflight_sql
from .rules.rollback import sibling_rollback
from .version import parse_version

_EXIT = {"safe": 0, "review": 1, "block": 2}
# ANSI colors: block red, warn / review yellow, safe green.
_COLORS = {"block": "31", "warn": "33", "review": "33", "safe": "32"}


def _use_color(choice: str) -> bool:
    """--color auto: only on a terminal, unless NO_COLOR is set (https://no-color.org)."""
    if choice != "auto":
        return choice == "always"
    if os.environ.get("NO_COLOR"):
        return False
    if os.environ.get("FORCE_COLOR"):
        return True
    return sys.stdout.isatty() and os.environ.get("TERM") != "dumb"


def _paint(text: str, level: str, on: bool, bold: bool = False) -> str:
    code = _COLORS.get(level)
    if not on or not code:
        return text
    return f"\033[{'1;' if bold else ''}{code}m{text}\033[0m"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="mysql-audit", description=__doc__.splitlines()[0])
    parser.add_argument("files", nargs="*", help="SQL files to review (stdin when omitted)")
    parser.add_argument("--schema", help="file with CREATE TABLE statements for the current schema")
    parser.add_argument("--stats", help='JSON file of table sizes: {"orders": 25000000} or {"orders": {"rows": ..., "data_bytes": ..., "index_bytes": ...}}')
    parser.add_argument("--preflight", action="store_true",
                        help="print SQL to run on the primary right before deploying these files, then exit")
    parser.add_argument("--code", action="store_true", help="files are application code: check for SQL injection")
    parser.add_argument("--mysql-version", help="target server, e.g. 8.0.28, 8.4.3 or aurora-3.04 (default: 8.0.29 or later)")
    parser.add_argument("--free-disk-gb", help="free space on the server's data volume, in GB (enables L17)")
    parser.add_argument("--config", help="settings file (default: the nearest .mysql-audit.toml)")
    parser.add_argument("--format", choices=("text", "json"), default="text")
    parser.add_argument("--color", choices=("auto", "always", "never"), default="auto",
                        help="color text output: block red, warn yellow (default: auto, only on a terminal)")
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
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
    if args.preflight:
        print(preflight_sql(";\n".join(sql for _, sql in sources), version))
        return 0

    worst = 0
    results = []
    for name, sql in sources:
        if args.code:
            report = review_code(sql)
        else:
            paired = name != "<stdin>" and sibling_rollback(Path(name)) is not None
            report = review(sql, schema=schema, stats=stats, mysql_version=version,
                            free_disk_gb=free_disk, has_rollback=paired)
        worst = max(worst, _EXIT[report.verdict])
        results.append({"file": name, **report.to_dict()})

    if args.format == "json":
        print(json.dumps(results if len(results) > 1 else results[0], indent=2, ensure_ascii=False))
    else:
        color = _use_color(args.color)
        if color and sys.platform == "win32":
            os.system("")  # turns on ANSI escape handling in the Windows console
        for r in results:
            counted = "" if args.code else f" ({r['statements']} statements)"
            verdict = _paint(r["verdict"].upper(), r["verdict"], color, bold=True)
            print(f"{r['file']}: {verdict}{counted}")
            for f in r["findings"]:
                line = f"  line {f['line']} [{f['severity']}] {f['rule_id']}: {f['message']}"
                print(_paint(line, f["severity"], color))
                print(f"    fix: {f['fix']}")
    return worst


if __name__ == "__main__":
    sys.exit(main())
