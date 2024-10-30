class RunCommandError(Exception):
    """Raised when runcommand returns stderr"""

    def __init__(self, error_msg: str, return_code: int):
        super().__init__(error_msg)

        self.return_code = return_code
        self.error_msg = error_msg
