class VLANError(Exception):
    """Raised when there's an error working with VLANs"""

    def __init__(
        self,
        error_msg: str,
    ):
        super().__init__(error_msg)
        self.error_msg = error_msg

class VLANCreationError(VLANError):
    pass

class VLANExistsError(VLANError):
    pass


class VLANNotFoundError(VLANError):
    """Raised when a VLAN is not found"""

    def __init__(
        self,
        error_msg: str = "VLAN not found",
    ):
        super().__init__(error_msg)
