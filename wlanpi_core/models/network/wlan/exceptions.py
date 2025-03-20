class WlanDBUSException(Exception):
    pass


class WlanDBUSInterfaceException(WlanDBUSException):
    pass


class WlanDBUSInterfaceCreationError(WlanDBUSInterfaceException):
    pass


class WDIScanError(WlanDBUSInterfaceException):
    pass


class WDIConnectionException(WlanDBUSInterfaceException):
    pass


class WDIDisconnectedException(WDIConnectionException):
    pass


class WDIAuthenticationError(WDIConnectionException):
    pass
