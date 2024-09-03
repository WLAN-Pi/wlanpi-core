class NetworkNamespaceError(Exception):
    """Raised when there's an error working with Network Namespaces"""

    def __init__(
        self,
        error_msg: str,
    ):
        super().__init__(error_msg)
        self.error_msg = error_msg


class NetworkNamespaceNotFoundError(NetworkNamespaceError):
    """Raised when a network namespace is not found"""

    def __init__(
        self,
        error_msg: str = "Network namespace not found",
    ):
        super().__init__(error_msg)
        self.error_msg = error_msg
