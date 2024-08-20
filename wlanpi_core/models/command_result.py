import json
from json import JSONDecodeError
from typing import Union


class CommandResult:
    """Returned by run_command"""

    def __init__(self, output: str, error: str, status_code: int):
        self.output = output
        self.error = error
        self.status_code = status_code
        self.success = self.status_code == 0

    def output_from_json(self) -> Union[dict, list, int, float, str, None]:
        try:
            return json.loads(self.output)
        except JSONDecodeError:
            return None
