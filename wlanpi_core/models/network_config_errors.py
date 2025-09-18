class ConfigActiveError(Exception):
    """Raised when trying to delete an active configuration."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message
