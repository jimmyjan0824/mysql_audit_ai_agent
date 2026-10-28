"""L13 and L16: statements that act on the whole server, replication or accounts."""

from __future__ import annotations

from ..analysis import Analyzed
from ..context import ScriptContext
from ..models import Finding, Severity
from .base import Rule, finding

_OFF = {"0", "OFF", "FALSE"}


# -- L13 -------------------------------------------------------------------

def _assignments(words: list[str]) -> list[tuple[str, str, str]]:
    """(scope, variable, value) for each assignment in a SET statement.

    Handles SET [GLOBAL|PERSIST|SESSION] var = v and SET @@[global.]var = v;
    a scope keyword carries over to later assignments, as in MySQL.
    """
    out: list[tuple[str, str, str]] = []
    scope = "SESSION"
    part: list[str] = []
    for word in words[1:] + [","]:
        if word != ",":
            part.append(word)
            continue
        if part and part[0] in ("GLOBAL", "PERSIST", "PERSIST_ONLY", "SESSION", "LOCAL"):
            scope = "SESSION" if part[0] == "LOCAL" else part[0]
            part = part[1:]
        if part[:1] == ["@@"]:
            part = part[1:]
            if len(part) > 2 and part[1] == ".":
                scope = "SESSION" if part[0] == "LOCAL" else part[0]
                part = part[2:]
        if len(part) >= 3 and part[1] in ("=", ":="):
            out.append((scope, part[0], part[2]))
        part = []
    return out


def _check_l13(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    if a.kind != "set":
        return []
    out = []
    for scope, var, value in _assignments(a.stmt.words):
        if var == "SQL_LOG_BIN" and value in _OFF:
            out.append(finding(
                "L13", Severity.BLOCK, a,
                "SET sql_log_bin = 0 keeps the following changes out of the binary log.",
                "Replicas never receive these changes, so their data silently diverges from the "
                "primary, and point-in-time recovery from the binlog cannot replay them.",
                "Remove it. Run the change with binary logging on so every replica applies it; "
                "if a change must stay local to one server, have a DBA run it by hand.",
            ))
        elif scope in ("GLOBAL", "PERSIST", "PERSIST_ONLY"):
            how = "and keeps it after a restart" if scope != "GLOBAL" else "until the next restart"
            out.append(finding(
                "L13", Severity.WARN, a,
                f"SET {scope} changes `{var.lower()}` for every connection on the server {how}.",
                "Every application and job on this server is affected, not just this migration, "
                "and the change stays after the script ends.",
                f"Use SET SESSION {var.lower()} = ... if only this script needs it. A server "
                "setting belongs in the configuration change process, reviewed by a DBA.",
            ))
    return out


L13 = Rule(
    id="L13",
    title="Turning off the binlog or changing server-wide settings",
    severity=Severity.BLOCK,
    why=(
        "SET sql_log_bin = 0 keeps a change out of the binary log, so replicas never apply it "
        "and drift from the primary without any error. SET GLOBAL and SET PERSIST change the "
        "setting for every connection on the server and outlive the migration."
    ),
    safe_example="SET SESSION lock_wait_timeout = 5;  -- session scope, binlog left on",
    check=_check_l13,
)


# -- L16 -------------------------------------------------------------------

def _accounts(words: list[str], start: int) -> list[str]:
    """user@host names after position start, as written (quotes removed)."""
    out, i = [], start
    while i < len(words):
        if words[i] in ("WITH", "REQUIRE", "IDENTIFIED", "AS"):
            break
        if i + 2 < len(words) and words[i + 1] == "@":
            out.append(f"{words[i].lower()}@{words[i + 2]}")
            i += 3
        else:
            i += 1
    return out


def _check_l16(a: Analyzed, ctx: ScriptContext) -> list[Finding]:
    w = a.stmt.words
    if w[:2] == ["DROP", "USER"]:
        names = _accounts(w, 2)
        return [finding(
            "L16", Severity.BLOCK, a,
            "This statement drops the account " + ", ".join(f"`{n}`" for n in names) + "."
            if names else "This statement drops a database account.",
            "Every application or job that logs in with it fails from that moment, and its "
            "privileges have to be rebuilt by hand to undo it.",
            "First lock it (ALTER USER ... ACCOUNT LOCK) and watch for failed logins; drop it "
            "in a later change once nothing uses it.",
        )]
    if w[0] != "GRANT" or "TO" not in w:
        return []
    to = w.index("TO")
    on = w.index("ON") if "ON" in w[:to] else None  # GRANT role TO user has no ON
    privs = w[1:on or to]
    target = w[on + 1:to] if on else []
    everything = "ALL" in privs and target[:3] == ["*", ".", "*"]
    any_host = [n for n in _accounts(w, to + 1) if n.endswith("@%")]
    grant_option = w[-3:] == ["WITH", "GRANT", "OPTION"]
    if everything:
        return [finding(
            "L16", Severity.BLOCK, a,
            "GRANT ALL ON *.* gives full control of every database on the server.",
            "Whoever holds the account can read and drop any data, create users and change "
            "server settings. A leaked application password becomes a full takeover.",
            "Grant only the privileges the application needs on its own database, for example "
            "GRANT SELECT, INSERT, UPDATE, DELETE ON shop.* TO 'app'@'10.0.%'.",
        )]
    problems = []
    if any_host:
        problems.append("can log in from any host (" + ", ".join(f"`{n}`" for n in any_host) + ")")
    if grant_option:
        problems.append("may pass its privileges on (WITH GRANT OPTION)")
    if not problems:
        return []
    return [finding(
        "L16", Severity.WARN, a,
        "This grant goes to an account that " + " and ".join(problems) + ".",
        "Anyone who obtains the password can use it from any network, or hand the access to "
        "other accounts.",
        "Limit the host to the application's network (for example 'app'@'10.0.%') and drop "
        "WITH GRANT OPTION.",
    )]


L16 = Rule(
    id="L16",
    title="Over-broad grants and dropped accounts",
    severity=Severity.BLOCK,
    why=(
        "GRANT ALL ON *.* hands over the whole server, and a host of '%' accepts logins from "
        "anywhere. DROP USER takes effect at once: everything that still logs in with the "
        "account fails, and the grants are lost."
    ),
    safe_example="GRANT SELECT, INSERT, UPDATE, DELETE ON shop.* TO 'app'@'10.0.%';",
    check=_check_l16,
)
