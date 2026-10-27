"""Rule registry. Rule ids follow the project plan (L01-L12)."""

from .base import Rule
from .data_safety import L06, L07, L08, L09
from .injection import L12, review_code
from .locking import L04, L05
from .online_ddl import L01, L02, L03
from .query import L11
from .types import L10

RULES: dict[str, Rule] = {r.id: r for r in (L01, L02, L03, L04, L05, L06, L07, L08, L09, L10, L11, L12)}

__all__ = ["RULES", "Rule", "review_code"]
