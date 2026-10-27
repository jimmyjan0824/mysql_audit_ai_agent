"""Rule registry. Rule ids follow the project plan (L01-L12); ids not listed
here are not implemented yet."""

from .base import Rule
from .data_safety import L07, L08
from .locking import L04, L05
from .online_ddl import L01, L02

RULES: dict[str, Rule] = {r.id: r for r in (L01, L02, L04, L05, L07, L08)}

__all__ = ["RULES", "Rule"]
