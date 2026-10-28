"""Rule registry. Rule ids follow the project plan (L01-L16)."""

from .base import Rule
from .data_safety import L06, L07, L08, L09
from .injection import L12, review_code
from .locking import L04, L05
from .online_ddl import L01, L02, L03
from .schema import L14, L15
from .server import L13, L16
from .query import L11
from .types import L10

RULES: dict[str, Rule] = {r.id: r for r in (L01, L02, L03, L04, L05, L06, L07, L08, L09, L10, L11, L12, L13, L14, L15, L16)}

__all__ = ["RULES", "Rule", "review_code"]
