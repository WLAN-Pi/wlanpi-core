"""Exit 0 when this WLAN Pi model may transmit, 1 when it may not.

`wpa_supplicant@wlan0.service` runs this as `ExecCondition`, so systemd skips
the unit on a Go or an unknown model.
"""

import sys

from wlanpi_core.core.transmit_policy import refusal_detail
from wlanpi_core.services.platform_cache import resolve_model


def main() -> int:
    """Print the refusal and return 1, or return 0 when transmit is allowed."""
    detail = refusal_detail(resolve_model())
    if detail is None:
        return 0
    print(detail, file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
