"""MySQL schema-change safety review for AI coding agents."""

from .engine import review
from .models import Finding, Report, Severity

__all__ = ["review", "Finding", "Report", "Severity"]
__version__ = "0.1.0"
