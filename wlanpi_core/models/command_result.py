"""Result object for executed commands."""

import json
import re
from json import JSONDecodeError
from re import RegexFlag
from typing import Any


class CommandResult:
    """Returned by run_command."""

    def __init__(self, stdout: str, stderr: str, return_code: int) -> None:
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.success = self.return_code == 0

    def output_from_json(
        self,
    ) -> dict[str, Any] | list[Any] | int | float | str | None:
        """Parse stdout as JSON, or return None on failure."""
        try:
            return json.loads(self.stdout)
        except JSONDecodeError:
            return None

    def grep_stdout_for_string(
        self, string: str, negate: bool = False, split: bool = False
    ) -> str | list[str]:
        """Filter stdout lines by substring match."""
        if negate:
            filtered = list(filter(lambda x: string not in x, self.stdout.split("\n")))
        else:
            filtered = list(filter(lambda x: string in x, self.stdout.split("\n")))
        return filtered if split else "\n".join(filtered)

    def grep_stdout_for_pattern(
        self,
        pattern: re.Pattern[str] | str,
        flags: int | RegexFlag = 0,
        negate: bool = False,
        split: bool = False,
    ) -> str | list[str]:
        """Filter stdout lines by regex match."""
        if negate:
            filtered = list(
                filter(
                    lambda x: not re.match(pattern, x, flags=flags),
                    self.stdout.split("\n"),
                )
            )
        else:
            filtered = list(
                filter(
                    lambda x: re.match(pattern, x, flags=flags), self.stdout.split("\n")
                )
            )
        return filtered if split else "\n".join(filtered)
