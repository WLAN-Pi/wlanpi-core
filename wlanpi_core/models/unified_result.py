from typing import Optional

class UnifiedResult:
    """Returned by anything"""
    def __init__(self, success: bool, data: Optional[str]=None, errors: Optional[list]=None ):
        if errors is None:
            errors = list()
        self.data = data
        self.errors = errors
        self.success = success

