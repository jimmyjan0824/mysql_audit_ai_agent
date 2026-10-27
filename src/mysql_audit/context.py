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
LARGE_TABLE_ROWS = 1_000_000  # above this, DDL and bulk writes need online tooling
SMALL_TABLE_ROWS = 10_000     # below this, a full scan is cheap

_SET_RE = re.compile(r"(lock_wait_timeout|foreign_key_checks)=([a-z0-9_]+)$")


@dataclass
class Column:
    type: exp.DataType
    charset: str | None = None
    nullable: bool = True


@dataclass
class ScriptContext:
    columns: dict[str, dict[str, Column]] = field(default_factory=dict)
    table_charset: dict[str, str] = field(default_factory=dict)
    created_tables: set[str] = field(default_factory=set)
    recreated: set[str] = field(default_factory=set)  # tables a CREATE TABLE in the script defines
    indexes: dict[str, list[list[str]]] = field(default_factory=dict)  # column lists, leftmost first
    uniques: dict[str, list[list[str]]] = field(default_factory=dict)  # primary key and unique keys
    rows: dict[str, int] = field(default_factory=dict)                 # approximate row counts
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

    def size(self, table: str | None) -> int | None:
        return self.rows.get(table) if table else None

    def is_large(self, table: str | None) -> bool:
        return (self.size(table) or 0) >= LARGE_TABLE_ROWS

    def is_small(self, table: str | None) -> bool:
        rows = self.size(table)
        return rows is not None and rows < SMALL_TABLE_ROWS

    def knows(self, table: str | None) -> bool:
        """True when the schema of the table was given or created in the script."""
        return table is not None and table in self.columns

    def add_index(self, table: str | None, cols: list[str], unique: bool = False) -> None:
        if table and cols:
            self.indexes.setdefault(table, []).append(cols)
            if unique:
                self.uniques.setdefault(table, []).append(cols)

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
        t = a.table
        cols: dict[str, Column] = {}
        self.indexes[t] = []
        self.uniques[t] = []
        for item in tree.this.expressions:
            if isinstance(item, exp.ColumnDef) and isinstance(item.kind, exp.DataType):
                name = item.name.lower()
                charset = None
                nullable = True
                for c in item.constraints:
                    if isinstance(c.kind, exp.CharacterSetColumnConstraint):
                        charset = c.kind.this.name.lower()
                    elif isinstance(c.kind, exp.NotNullColumnConstraint) and not c.kind.args.get("allow_null"):
                        nullable = False
                    elif isinstance(c.kind, (exp.PrimaryKeyColumnConstraint, exp.UniqueColumnConstraint)):
                        if isinstance(c.kind, exp.PrimaryKeyColumnConstraint):
                            nullable = False
                        self.add_index(t, [name], unique=True)
                cols[name] = Column(item.kind, charset, nullable)
            elif isinstance(item, exp.PrimaryKey):
                self.add_index(t, _names(item.expressions), unique=True)
            elif isinstance(item, exp.UniqueColumnConstraint) and isinstance(item.this, exp.Schema):
                self.add_index(t, _names(item.this.expressions), unique=True)
            elif isinstance(item, exp.IndexColumnConstraint):
                self.add_index(t, _names(item.expressions))
            elif isinstance(item, exp.ForeignKey):
                # InnoDB creates an index for a foreign key when none exists.
                self.add_index(t, _names(item.expressions))
        self.columns[t] = cols
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
        elif a.kind == "create_index":
            self.add_index(a.table, a.index_columns, unique="UNIQUE" in a.stmt.words[:3])
        elif a.kind == "alter_table":
            for c in a.clauses:
                if c.kind in ("add_index", "add_pk"):
                    self.add_index(a.table, c.index_columns, unique=c.kind == "add_pk" or "UNIQUE" in c.words)

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


def _names(items: list[exp.Expression]) -> list[str]:
    """Column names of a key definition; DESC and prefix lengths are dropped."""
    names = []
    for item in items:
        col = item.find(exp.Column) or item.find(exp.Identifier) or item
        names.append(col.name.lower())
    return names
