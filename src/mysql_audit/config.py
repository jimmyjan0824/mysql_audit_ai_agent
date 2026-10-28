"""Project settings from .mysql-audit.toml, so the version, schema and stats are
given once instead of on every run.

    # .mysql-audit.toml, at the repository root
    mysql_version = "8.0.28"
    schema = "db/schema.sql"        # relative to this file
    stats = "db/table_stats.json"

Command-line options and tool arguments override these. MYSQL_AUDIT_VERSION in
the environment overrides mysql_version (handy in an MCP client's config).
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path

if sys.version_info >= (3, 11):
    import tomllib
else:  # pragma: no cover
    import tomli as tomllib

CONFIG_NAME = ".mysql-audit.toml"
_KEYS = {"mysql_version", "schema", "stats"}


@dataclass
class Config:
    mysql_version: str | None = None
    schema: str | None = None          # CREATE TABLE text
    stats: dict | None = None
    path: Path | None = None           # the file these came from
    files: tuple[Path, ...] = ()       # schema / stats files it names (not migrations)


def find_config(start: Path) -> Path | None:
    """The nearest .mysql-audit.toml in start or a parent, stopping at the repository root."""
    for d in [start, *start.parents]:
        if (d / CONFIG_NAME).is_file():
            return d / CONFIG_NAME
        if (d / ".git").exists():
            return None
    return None


def load_config(start: Path | None = None, path: Path | None = None, env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    path = path or find_config((start or Path.cwd()).resolve())
    cfg = Config(path=path)
    if path is not None:
        with open(path, "rb") as f:
            data = tomllib.load(f)
        unknown = set(data) - _KEYS
        if unknown:
            raise ValueError(f"{path}: unknown setting(s) {', '.join(sorted(unknown))}; "
                             f"known: {', '.join(sorted(_KEYS))}")
        base = path.parent
        cfg.mysql_version = data.get("mysql_version")
        if data.get("schema"):
            cfg.schema = (base / data["schema"]).read_text(encoding="utf-8")
            cfg.files += ((base / data["schema"]).resolve(),)
        if data.get("stats"):
            cfg.stats = json.loads((base / data["stats"]).read_text(encoding="utf-8"))
            cfg.files += ((base / data["stats"]).resolve(),)
    if env.get("MYSQL_AUDIT_VERSION"):
        cfg.mysql_version = env["MYSQL_AUDIT_VERSION"]
    return cfg
