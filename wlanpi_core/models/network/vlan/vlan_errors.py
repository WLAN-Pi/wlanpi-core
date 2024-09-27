class VLANError(Exception):
    """Raised when there's an error working with VLANs"""

    def __init__(
        self,
        error_msg: str,
        status_code: int=500,
    ):
        super().__init__(error_msg)
        self.error_msg = error_msg
        self.status_code = status_code

class VLANCreationError(VLANError):
    pass

class VLANDeletionError(VLANError):
    pass

class VLANExistsError(VLANError):
    def __init__(
            self,
            error_msg: str = "VLAN exists",
            status_code: int = 400,
    ):
        super().__init__(error_msg=error_msg, status_code=status_code)


class VLANNotFoundError(VLANError):
    """Raised when a VLAN is not found"""

    def __init__(
        self,
        error_msg: str = "VLAN not found",
        status_code: int=400,
    ):
        super().__init__(error_msg=error_msg, status_code=status_code)
