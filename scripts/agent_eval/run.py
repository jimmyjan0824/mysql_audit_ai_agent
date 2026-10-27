"""Run each scenario through Claude Code headless, with and without the
mysql-audit MCP server, and score the result.

    python scripts/agent_eval/run.py --model sonnet --jobs 4 --out results.json

Scores per run: did the agent call a mysql-audit tool, and is the file it
wrote free of block findings (review / review_code with the schema and stats).
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import pathlib
import subprocess
import tempfile

from scenarios import CONTEXT, SCENARIOS, SCHEMA, STATS

from mysql_audit import review, review_code

MCP_CONFIG = {"mcpServers": {"mysql-audit": {"command": "mysql-audit-mcp"}}}
TOOLS = "Read,Write,Edit,Glob,Grep"


def run_one(name: str, output: str, prompt: str, with_tool: bool, model: str) -> dict:
    work = pathlib.Path(tempfile.mkdtemp(prefix=f"agent-{name}-"))
    (work / "schema.sql").write_text(SCHEMA)
    (work / "stats.json").write_text(json.dumps(STATS, indent=2))
    cmd = ["claude", "-p", CONTEXT + prompt + f" Write it to {output}.", "--model", model,
           "--output-format", "stream-json", "--verbose", "--permission-mode", "acceptEdits",
           "--strict-mcp-config", "--setting-sources", ""]
    allowed = TOOLS
    if with_tool:
        cfg = work.parent / f"{work.name}-mcp.json"
        cfg.write_text(json.dumps(MCP_CONFIG))
        cmd += ["--mcp-config", str(cfg)]
        allowed += ",mcp__mysql-audit"
    cmd += ["--allowedTools", allowed]
    proc = subprocess.run(cmd, cwd=work, capture_output=True, text=True, timeout=900)

    tool_calls, final_text = [], ""
    for line in proc.stdout.splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        if event.get("type") == "assistant":
            for block in event["message"].get("content", []):
                if block.get("type") == "tool_use" and block["name"].startswith("mcp__mysql-audit"):
                    tool_calls.append(block["name"].split("__")[-1])
        if event.get("type") == "result":
            final_text = event.get("result", "")

    path = work / output
    written = path.read_text() if path.exists() else ""
    if not written:
        verdict, rules = "missing", []
    else:
        report = review_code(written) if output.endswith(".py") else review(written, schema=SCHEMA, stats=STATS)
        verdict = report.verdict
        rules = sorted({f"{f.rule_id}:{f.severity.value}" for f in report.findings})
    return {
        "scenario": name, "with_tool": with_tool, "tool_calls": tool_calls, "verdict": verdict,
        "rules": rules, "file": written, "final_text": final_text[-1500:], "dir": str(work),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--jobs", type=int, default=4)
    parser.add_argument("--only", nargs="*")
    parser.add_argument("--baseline", action="store_true", help="also run without the MCP server")
    parser.add_argument("--out", default="results.json")
    args = parser.parse_args()

    runs = [(n, o, p, True) for n, o, p in SCENARIOS if not args.only or n in args.only]
    if args.baseline:
        runs += [(n, o, p, False) for n, o, p, _ in runs]
    with concurrent.futures.ThreadPoolExecutor(args.jobs) as pool:
        results = list(pool.map(lambda r: run_one(*r, args.model), runs))
    pathlib.Path(args.out).write_text(json.dumps(results, indent=2, ensure_ascii=False))
    for r in results:
        mode = "tool" if r["with_tool"] else "base"
        print(f"{r['scenario']:14} {mode}  calls={len(r['tool_calls']):2}  verdict={r['verdict']:7}  {' '.join(r['rules'])}")


if __name__ == "__main__":
    main()
