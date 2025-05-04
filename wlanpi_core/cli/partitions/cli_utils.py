import sys

BLUE = "\033[1;34m"
GREEN = "\033[1;32m"
YELLOW = "\033[1;33m"
RED = "\033[1;31m"
CYAN = "\033[1;36m"
RESET = "\033[0m"

def echo_status(msg: str) -> None:
    print(f"{BLUE}>>> {msg}{RESET}")

def echo_debug(msg: str) -> None:
    print(f"{CYAN}DEBUG: {msg}{RESET}")

def echo_warning(msg: str) -> None:
    print(f"{YELLOW}WARNING: {msg}{RESET}")

def echo_error(msg: str) -> None:
    print(f"{RED}ERROR: {msg}{RESET}")
    sys.exit(1)
