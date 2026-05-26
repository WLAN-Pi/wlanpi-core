class ConfigActiveError(Exception):
    """Raised when trying to delete an active configuration."""

    def __init__(self, message: str):
        super().__init__(message)
        self.message = message


class ConfigMalformedError(Exception):
    """Raised when a configuration file is malformed or invalid."""

    def __init__(self, message: str, cfg_id: str = None):
        super().__init__(message)
        self.message = message
        self.cfg_id = cfg_id
