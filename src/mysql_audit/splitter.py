"""Split a SQL script into statements, keeping line numbers and tokens.

The sqlglot MySQL tokenizer is used so that semicolons inside strings and
comments do not split a statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from sqlglot.dialects.mysql import MySQL
from sqlglot.tokens import Token, TokenType



class _Tokenizer(MySQL.Tokenizer):
    # sqlglot treats RENAME as an opaque command and swallows the rest of the
    # statement into one string; tokenize it like any other statement.
    COMMANDS = MySQL.Tokenizer.COMMANDS - {TokenType.RENAME}


_TOKENIZER = _Tokenizer()


def _split_keywords(tokens: list[Token]) -> list[Token]:
    """Split multi-word keyword tokens ("PRIMARY KEY", "FOREIGN KEY") into one
    token per word, so rules can match keywords one word at a time."""
    out: list[Token] = []
    for tok in tokens:
        if tok.token_type in (TokenType.STRING, TokenType.IDENTIFIER) or " " not in tok.text.strip():
            out.append(tok)
            continue
        for word in tok.text.split():
            out.append(Token(tok.token_type, word, tok.line, tok.col, tok.start, tok.end))
    return out


@dataclass
class Statement:
    sql: str
    line: int
    tokens: list[Token]
    offset: int  # position of the statement's first character in the script

    def text_of(self, first: Token, last: Token) -> str:
        """Original text from first to last token, quotes and spacing kept."""
        return self.sql[first.start - self.offset : last.end + 1 - self.offset]

    @property
    def words(self) -> list[str]:
        """Upper-cased token texts, for keyword matching."""
        return [t.text.upper() for t in self.tokens]


_DELIMITER_RE = re.compile(r"^[ \t]*DELIMITER[ \t]+(\S+)[ \t]*$", re.I | re.M)


def split_statements(sql: str) -> list[Statement]:
    """Split a script into statements.

    Supports the mysql client's DELIMITER command: text between
    `DELIMITER ;;` and `DELIMITER ;` is split on the custom delimiter, so a
    stored routine stays one statement. Routine bodies are not analysed.
    """
    plain = list(sql)
    routines: list[tuple[int, str]] = []  # (offset, text) of custom-delimiter statements
    delimiter = ";"
    region_start = 0
    for m in list(_DELIMITER_RE.finditer(sql)) + [None]:
        region_end = m.start() if m else len(sql)
        if delimiter != ";":
            pos = region_start
            for piece in sql[region_start:region_end].split(delimiter):
                if piece.strip():
                    routines.append((pos, piece))
                pos += len(piece) + len(delimiter)
            _blank(plain, region_start, region_end)
        if m:
            _blank(plain, m.start(), m.end())
            delimiter = m.group(1)
            region_start = m.end()

    statements = _split_plain("".join(plain))
    for offset, piece in routines:
        statements.extend(_routine(sql, offset, piece))
    statements.sort(key=lambda st: st.offset)
    return statements


def _blank(chars: list[str], start: int, end: int) -> None:
    """Hide a span from the tokenizer, keeping offsets and line numbers."""
    for i in range(start, end):
        if chars[i] != "\n":
            chars[i] = " "


def _split_plain(sql: str) -> list[Statement]:
    tokens = _split_keywords(_TOKENIZER.tokenize(sql))
    statements: list[Statement] = []
    current: list[Token] = []
    for tok in tokens + [None]:
        if tok is None or tok.token_type == TokenType.SEMICOLON:
            if current:
                text = sql[current[0].start : current[-1].end + 1]
                statements.append(Statement(sql=text, line=current[0].line, tokens=current, offset=current[0].start))
            current = []
        else:
            current.append(tok)
    return statements


def _routine(sql: str, offset: int, piece: str) -> list[Statement]:
    try:
        raw = _TOKENIZER.tokenize(piece)
    except Exception:
        return []
    if not raw:
        return []
    line0 = sql.count("\n", 0, offset)
    tokens = [Token(t.token_type, t.text, t.line + line0, t.col, t.start + offset, t.end + offset) for t in raw]
    tokens = _split_keywords(tokens)
    text = sql[tokens[0].start : tokens[-1].end + 1]
    return [Statement(sql=text, line=tokens[0].line, tokens=tokens, offset=tokens[0].start)]


def split_top_level(tokens: list[Token]) -> list[list[Token]]:
    """Split tokens on commas that are not inside parentheses."""
    parts: list[list[Token]] = []
    current: list[Token] = []
    depth = 0
    for tok in tokens:
        if tok.token_type == TokenType.L_PAREN:
            depth += 1
        elif tok.token_type == TokenType.R_PAREN:
            depth -= 1
        if tok.token_type == TokenType.COMMA and depth == 0:
            parts.append(current)
            current = []
        else:
            current.append(tok)
    if current:
        parts.append(current)
    return parts


def read_table_name(tokens: list[Token], i: int) -> tuple[str | None, int]:
    """Read a possibly qualified table name (db.t) starting at tokens[i].

    Returns the lower-cased name without the schema and the index after it.
    """
    if i >= len(tokens):
        return None, i
    name = tokens[i].text
    i += 1
    while i + 1 < len(tokens) and tokens[i].token_type == TokenType.DOT:
        name = tokens[i + 1].text
        i += 2
    return name.lower(), i
