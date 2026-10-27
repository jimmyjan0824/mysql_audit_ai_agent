"""Run the engine over real-world migration files and summarise the findings.

Used to measure noise and false positives before a release:

    git clone --depth 1 https://github.com/apolloconfig/apollo /tmp/apollo
    python scripts/corpus_eval.py /tmp/apollo/scripts/sql/profiles/mysql-default --samples 3
"""

from __future__ import annotations

import argparse
import collections
import pathlib

from mysql_audit import review


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("dirs", nargs="+", help="directories searched for *.sql")
    parser.add_argument("--samples", type=int, default=0, help="example findings to print per rule and severity")
    args = parser.parse_args()

    counts: collections.Counter = collections.Counter()
    samples: dict = collections.defaultdict(list)
    files = statements = 0
    errors = []
    for d in args.dirs:
        for path in sorted(pathlib.Path(d).rglob("*.sql")):
            files += 1
            try:
                report = review(path.read_text(encoding="utf-8", errors="replace"))
            except Exception as e:  # a crash is a bug worth reporting, keep going
                errors.append(f"{path}: {e!r}")
                continue
            statements += report.statements
            for f in report.findings:
                key = (f.rule_id, f.severity.value)
                counts[key] += 1
                if len(samples[key]) < args.samples:
                    samples[key].append(f"{path}:{f.line}  {f.statement[:100]}")

    print(f"{files} files, {statements} statements, {len(errors)} crashes")
    for e in errors:
        print("CRASH", e)
    for (rule, severity), n in sorted(counts.items()):
        print(f"{rule} {severity:5} {n}")
        for s in samples[(rule, severity)]:
            print("     ", s)


if __name__ == "__main__":
    main()
