"""MySQL schema-change safety review for AI coding agents."""

from .engine import review, review_code
from .models import Finding, Report, Severity

__all__ = ["review", "review_code", "Finding", "Report", "Severity"]
__version__ = "0.2.1"
