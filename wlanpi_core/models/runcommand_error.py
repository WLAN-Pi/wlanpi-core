"""Error raised when a command fails."""


class RunCommandError(Exception):
    """Raised when runcommand returns stderr."""

    def __init__(self, error_msg: str, return_code: int):
        super().__init__(error_msg)

        self.return_code = return_code
        self.error_msg = error_msg

    def __str__(self) -> str:
        """Return the error message with its exit code."""
        return f"{self.error_msg} (exit code {self.return_code})"
