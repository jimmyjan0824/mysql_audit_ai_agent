"""Turn a raw statement into the facts the rules need.

DDL is read from tokens rather than from a full parse tree: sqlglot does
not model every MySQL ALTER TABLE clause (ALGORITHM, LOCK, CHANGE ...), and
a rule must never miss a clause because the parser skipped it. DML and
CREATE TABLE go through sqlglot, which handles them well.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import sqlglot
from sqlglot import exp
from sqlglot.tokens import Token, TokenType

from .splitter import Statement, read_table_name, split_top_level

# Words that end the data type part of a column definition.
_TYPE_STOP_WORDS = {
    "NULL", "NOT", "DEFAULT", "COMMENT", "AFTER", "FIRST", "AUTO_INCREMENT",
    "PRIMARY", "UNIQUE", "KEY", "COLLATE", "CHARACTER", "CHARSET", "GENERATED",
    "AS", "VISIBLE", "INVISIBLE", "ON", "REFERENCES", "CHECK", "CONSTRAINT",
    "STORAGE", "COLUMN_FORMAT", "SRID", "ENGINE_ATTRIBUTE",
}


@dataclass
class AlterClause:
    kind: str
    tokens: list[Token]
    column: str | None = None       # column the clause acts on
    new_column: str | None = None   # CHANGE / RENAME COLUMN target name
    type_sql: str | None = None     # MODIFY / CHANGE new type, as written
    charset: str | None = None      # MODIFY / CHANGE / CONVERT charset, if given
    index_columns: list[str] = field(default_factory=list)  # ADD INDEX / PRIMARY KEY columns

    @property
    def words(self) -> list[str]:
        return [t.text.upper() for t in self.tokens]


@dataclass
class Analyzed:
    stmt: Statement
    kind: str
    tables: list[str] = field(default_factory=list)
    clauses: list[AlterClause] = field(default_factory=list)
    algorithm: str | None = None
    lock: str | None = None
    temporary: bool = False
    tree: exp.Expression | None = None
    index_columns: list[str] = field(default_factory=list)  # CREATE INDEX columns

    @property
    def table(self) -> str | None:
        return self.tables[0] if self.tables else None


def analyze(stmt: Statement) -> Analyzed:
    w = stmt.words
    toks = stmt.tokens

    if w[:2] == ["ALTER", "TABLE"]:
        return _analyze_alter(stmt)

    if w[0] == "CREATE":
        i = 1
        temporary = False
        if i < len(w) and w[i] == "TEMPORARY":
            temporary = True
            i += 1
        if i < len(w) and w[i] == "TABLE":
            i += 1
            if w[i : i + 3] == ["IF", "NOT", "EXISTS"]:
                i += 3
            name, _ = read_table_name(toks, i)
            return Analyzed(stmt, "create_table", [name] if name else [], temporary=temporary,
                            tree=_parse(stmt))
        if "VIEW" in w[:8]:
            name, _ = read_table_name(toks, w.index("VIEW") + 1)
            return Analyzed(stmt, "create_view", [name] if name else [])
        if "INDEX" in w[:4] and "ON" in w:
            name, _ = read_table_name(toks, w.index("ON") + 1)
            a = Analyzed(stmt, "create_index", [name] if name else [])
            a.algorithm, a.lock = _options(w)
            a.index_columns = _key_columns(toks)
            return a

    if w[:2] == ["DROP", "INDEX"] and "ON" in w:
        name, _ = read_table_name(toks, w.index("ON") + 1)
        a = Analyzed(stmt, "drop_index", [name] if name else [])
        a.algorithm, a.lock = _options(w)
        return a

    if w[0] == "DROP" and ("TABLE" in w[1:3]):
        i = w.index("TABLE") + 1
        if w[i : i + 2] == ["IF", "EXISTS"]:
            i += 2
        tables = [n for part in split_top_level(toks[i:]) if (n := read_table_name(part, 0)[0])]
        return Analyzed(stmt, "drop_table", tables, temporary=w[1] == "TEMPORARY")

    if w[0] == "DROP" and len(w) > 1 and w[1] in ("DATABASE", "SCHEMA"):
        return Analyzed(stmt, "drop_database")

    if w[:2] == ["RENAME", "TABLE"]:
        tables = [n for part in split_top_level(toks[2:]) if (n := read_table_name(part, 0)[0])]
        return Analyzed(stmt, "rename_table", tables)

    if w[0] == "TRUNCATE":
        i = 2 if len(w) > 1 and w[1] == "TABLE" else 1
        name, _ = read_table_name(toks, i)
        return Analyzed(stmt, "truncate", [name] if name else [])

    if w[0] in ("UPDATE", "DELETE"):
        return Analyzed(stmt, w[0].lower(), tree=_parse(stmt))

    if w[0] in ("SELECT", "WITH"):
        return Analyzed(stmt, "select", tree=_parse(stmt))

    if w[0] in ("INSERT", "REPLACE"):
        return Analyzed(stmt, "insert", tree=_parse(stmt))

    if w[0] == "SET":
        return Analyzed(stmt, "set")

    return Analyzed(stmt, "other")


def _parse(stmt: Statement) -> exp.Expression | None:
    try:
        return sqlglot.parse_one(stmt.sql, read="mysql")
    except Exception:
        return None


def _options(words: list[str]) -> tuple[str | None, str | None]:
    """Find ALGORITHM= and LOCK= values anywhere in a statement."""
    found: dict[str, str] = {}
    for i, word in enumerate(words):
        if word in ("ALGORITHM", "LOCK") and i + 1 < len(words):
            j = i + 2 if words[i + 1] == "=" else i + 1
            if j < len(words):
                found[word] = words[j]
    return found.get("ALGORITHM"), found.get("LOCK")


def _analyze_alter(stmt: Statement) -> Analyzed:
    toks = stmt.tokens
    name, i = read_table_name(toks, 2)
    a = Analyzed(stmt, "alter_table", [name] if name else [])
    for part in split_top_level(toks[i:]):
        if part:
            clause = _classify(stmt, part)
            a.clauses.append(clause)
    a.algorithm, a.lock = _options(stmt.words)
    return a


def _classify(stmt: Statement, part: list[Token]) -> AlterClause:
    w = [t.text.upper() for t in part]
    head = w[0]
    nxt = w[1] if len(w) > 1 else ""

    if head in ("ALGORITHM", "LOCK"):
        return AlterClause("option", part)

    if head == "ADD":
        if nxt in ("INDEX", "KEY", "UNIQUE", "FULLTEXT", "SPATIAL"):
            return AlterClause("add_index", part, index_columns=_key_columns(part))
        if nxt == "PRIMARY":
            return AlterClause("add_pk", part, index_columns=_key_columns(part))
        if nxt == "FOREIGN" or (nxt == "CONSTRAINT" and "FOREIGN" in w):
            return AlterClause("add_fk", part)
        if nxt == "CONSTRAINT":
            if "PRIMARY" in w:
                return AlterClause("add_pk", part, index_columns=_key_columns(part))
            if "UNIQUE" in w:
                return AlterClause("add_index", part, index_columns=_key_columns(part))
            return AlterClause("add_check", part)
        if nxt in ("CHECK", "PARTITION"):
            return AlterClause("other", part)
        j = 2 if nxt == "COLUMN" else 1
        clause = AlterClause("add_column", part, column=_ident(part, j))
        _read_type(stmt, clause, part, j + 1)
        return clause

    if head == "DROP":
        if nxt in ("INDEX", "KEY"):
            return AlterClause("drop_index", part)
        if nxt == "PRIMARY":
            return AlterClause("drop_pk", part)
        if nxt == "FOREIGN":
            return AlterClause("drop_fk", part)
        if nxt in ("CONSTRAINT", "CHECK", "PARTITION"):
            return AlterClause("other", part)
        j = 2 if nxt == "COLUMN" else 1
        return AlterClause("drop_column", part, column=_ident(part, j))

    if head == "MODIFY":
        j = 2 if nxt == "COLUMN" else 1
        clause = AlterClause("modify", part, column=_ident(part, j))
        _read_type(stmt, clause, part, j + 1)
        return clause

    if head == "CHANGE":
        j = 2 if nxt == "COLUMN" else 1
        clause = AlterClause("change", part, column=_ident(part, j), new_column=_ident(part, j + 1))
        _read_type(stmt, clause, part, j + 2)
        return clause

    if head == "RENAME":
        if nxt == "COLUMN":
            return AlterClause("rename_column", part, column=_ident(part, 2), new_column=_ident(part, 4))
        if nxt in ("INDEX", "KEY"):
            return AlterClause("rename_index", part)
        return AlterClause("rename_table", part)

    if head == "CONVERT":
        clause = AlterClause("convert_charset", part)
        clause.charset = _charset_after(w)
        return clause

    if head == "ALTER":
        return AlterClause("alter_column", part)

    if head in ("ENGINE", "FORCE"):
        return AlterClause("rebuild", part)

    return AlterClause("other", part)


def _ident(part: list[Token], j: int) -> str | None:
    return part[j].text.lower() if j < len(part) else None


def _read_type(stmt: Statement, clause: AlterClause, part: list[Token], start: int) -> None:
    depth = 0
    end = start
    while end < len(part):
        tok = part[end]
        if tok.token_type == TokenType.L_PAREN:
            depth += 1
        elif tok.token_type == TokenType.R_PAREN:
            depth -= 1
        elif depth == 0 and tok.text.upper() in _TYPE_STOP_WORDS:
            break
        end += 1
    if end > start:
        clause.type_sql = stmt.text_of(part[start], part[end - 1])
    clause.charset = _charset_after([t.text.upper() for t in part])


def _charset_after(words: list[str]) -> str | None:
    for i, word in enumerate(words):
        if word == "CHARSET" and i + 1 < len(words):
            j = i + 2 if words[i + 1] == "=" else i + 1
            return words[j].lower() if j < len(words) else None
        if word == "CHARACTER" and i + 2 < len(words) and words[i + 1] == "SET":
            j = i + 3 if i + 3 < len(words) and words[i + 2] == "=" else i + 2
            return words[j].lower()
    return None


def _key_columns(tokens: list[Token]) -> list[str]:
    """Column names inside the first parenthesised key list: (a, b(10) DESC)."""
    cols: list[str] = []
    depth = 0
    expect_name = False
    for tok in tokens:
        if tok.token_type == TokenType.L_PAREN:
            depth += 1
            if depth == 1:
                expect_name = True
            continue
        if tok.token_type == TokenType.R_PAREN:
            depth -= 1
            if depth == 0 and cols:
                break
            continue
        if depth == 1:
            if tok.token_type == TokenType.COMMA:
                expect_name = True
            elif expect_name:
                cols.append(tok.text.lower())
                expect_name = False
    return cols
