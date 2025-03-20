from typing import Optional


class RunCommandError(Exception):
    """Raised when runcommand returns stderr"""

    def __init__(self, error_msg: str, return_code: int):
        super().__init__(error_msg)

        self.return_code = return_code
        self.error_msg = error_msg


class RunCommandTimeout(RunCommandError):
    """Raised when runcommand times out"""

    def __init__(self, error_msg: Optional[str]):
        if error_msg is None:
            error_msg = "The command timed out"
        super().__init__(error_msg, return_code=124)
