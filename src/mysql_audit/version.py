"""MySQL server versions, and what each one can do without copying the table."""

from __future__ import annotations

import re
from dataclasses import dataclass

# Aurora MySQL 3 releases and the community version each is compatible with.
# Only the 8.0.29 boundary matters to the rules: 3.05 and later are past it.
_AURORA_3 = {1: (8, 0, 23), 2: (8, 0, 23), 3: (8, 0, 26), 4: (8, 0, 28)}


@dataclass(frozen=True, order=True)
class Version:
    major: int
    minor: int
    patch: int

    def __str__(self) -> str:
        return f"{self.major}.{self.minor}.{self.patch}"

    @property
    def instant_add_last(self) -> bool:
        """ADD COLUMN at the end of the table runs INSTANT (8.0.12+)."""
        return self >= Version(8, 0, 12)

    @property
    def instant_add_anywhere(self) -> bool:
        """ADD COLUMN ... AFTER / FIRST and DROP COLUMN run INSTANT (8.0.29+)."""
        return self >= Version(8, 0, 29)


def parse_version(text: str) -> Version:
    """Parse "8.0.28", "8.4", "5.7.44-log", "aurora-3.04" or "aurora-2.11"."""
    s = text.strip().lower()
    m = re.fullmatch(r"aurora(?:-mysql)?[- ]?v?(\d+)(?:\.(\d+))?(?:\.\d+)*", s)
    if m:
        major, minor = int(m.group(1)), int(m.group(2) or 0)
        if major == 2:
            return Version(5, 7, 12)
        if major == 3:
            return Version(*_AURORA_3.get(minor, (8, 0, 32)))
        raise ValueError(f"unknown Aurora MySQL version {text!r}")
    m = re.match(r"(\d+)\.(\d+)(?:\.(\d+))?", s)
    if not m:
        raise ValueError(f"cannot read MySQL version {text!r}; use a form like 8.0.28 or aurora-3.04")
    major, minor = int(m.group(1)), int(m.group(2))
    if (major, minor) == (8, 0) and m.group(3) is None:
        raise ValueError("give the full 8.0 version, e.g. 8.0.28: INSTANT support changed within 8.0")
    return Version(major, minor, int(m.group(3) or 0))
