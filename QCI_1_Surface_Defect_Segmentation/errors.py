"""Small structured error hierarchy for recoverable samples and fatal config."""
from __future__ import annotations

from .contracts import Issue


class ConfigurationError(ValueError):
    """Fatal unsafe/missing configuration; no source files are changed."""


class InvalidSampleError(ValueError):
    """Recoverable sample failure with a machine-readable reason."""

    def __init__(self, issue: Issue) -> None:
        super().__init__(issue.message)
        self.issue = issue
