"""A unified result wrapper used across the API."""

from typing import Any


class UnifiedResult:
    """Returned by anything."""

    def __init__(
        self,
        success: bool,
        data: str | None = None,
        errors: list[Any] | None = None,
    ):
        if errors is None:
            errors = []
        self.data = data
        self.errors = errors
        self.success = success
