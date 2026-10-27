"""What the engine knows while it walks a script: the schema it was given,
tables the script itself creates, and session settings the script SETs."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from sqlglot import exp

from .analysis import Analyzed
from .splitter import split_top_level

# Bytes per character, for the VARCHAR length-prefix boundary (255 bytes).
CHARSET_MAXLEN = {
    "latin1": 1, "ascii": 1, "binary": 1, "utf8": 3, "utf8mb3": 3, "utf8mb4": 4,
    "ucs2": 2, "utf16": 4, "utf32": 4, "gbk": 2, "big5": 2, "sjis": 2,
}
DEFAULT_CHARSET = "utf8mb4"  # MySQL 8.0 default

_SET_RE = re.compile(r"(lock_wait_timeout|foreign_key_checks)=([a-z0-9_]+)$")


@dataclass
class Column:
    type: exp.DataType
    charset: str | None = None


@dataclass
class ScriptContext:
    columns: dict[str, dict[str, Column]] = field(default_factory=dict)
    table_charset: dict[str, str] = field(default_factory=dict)
    created_tables: set[str] = field(default_factory=set)
    lock_wait_timeout: int | None = None
    fk_checks_off: bool = False
    reported: set[str] = field(default_factory=set)  # once-per-script rules

    def is_new(self, table: str | None) -> bool:
        """Tables created earlier in the same script are empty: no lock risk."""
        return table is not None and table in self.created_tables

    def column(self, table: str | None, name: str | None) -> Column | None:
        if table is None or name is None:
            return None
        return self.columns.get(table, {}).get(name)

    def charset_of(self, table: str | None, col: Column | None) -> str:
        if col is not None and col.charset:
            return col.charset
        return self.table_charset.get(table or "", DEFAULT_CHARSET)

    # -- updates ---------------------------------------------------------

    def learn_schema(self, a: Analyzed) -> None:
        """Record columns of a CREATE TABLE statement."""
        if a.kind != "create_table" or a.table is None:
            return
        tree = a.tree
        if not isinstance(tree, exp.Create) or not isinstance(tree.this, exp.Schema):
            return
        cols: dict[str, Column] = {}
        for coldef in tree.this.expressions:
            if not isinstance(coldef, exp.ColumnDef) or not isinstance(coldef.kind, exp.DataType):
                continue
            charset = None
            for c in coldef.constraints:
                if isinstance(c.kind, exp.CharacterSetColumnConstraint):
                    charset = c.kind.this.name.lower()
            cols[coldef.name.lower()] = Column(coldef.kind, charset)
        self.columns[a.table] = cols
        props = tree.args.get("properties")
        if props:
            for p in props.expressions:
                if isinstance(p, exp.CharacterSetProperty):
                    self.table_charset[a.table] = p.this.name.lower()

    def update(self, a: Analyzed) -> None:
        """Apply the effects of a statement that has already been checked."""
        if a.kind == "create_table":
            if a.table:
                self.created_tables.add(a.table)
            self.learn_schema(a)
        elif a.kind == "set":
            self._apply_set(a)

    def _apply_set(self, a: Analyzed) -> None:
        for part in split_top_level(a.stmt.tokens[1:]):
            text = "".join(t.text for t in part).lower()
            if "global" in text or "persist" in text:
                continue
            m = _SET_RE.search(text)
            if not m:
                continue
            name, value = m.groups()
            if name == "lock_wait_timeout" and value.isdigit():
                self.lock_wait_timeout = int(value)
            elif name == "foreign_key_checks":
                self.fk_checks_off = value in ("0", "off", "false")
