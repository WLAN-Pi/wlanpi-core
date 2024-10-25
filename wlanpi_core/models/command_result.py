import json
from json import JSONDecodeError
from typing import Union


class CommandResult:
    """Returned by run_command"""

    def __init__(self, stdout: str, stderr: str, return_code: int):
        self.stdout = stdout
        self.stderr = stderr
        self.return_code = return_code
        self.success = self.return_code == 0

    def output_from_json(self) -> Union[dict, list, int, float, str, None]:
        try:
            return json.loads(self.stdout)
        except JSONDecodeError:
            return None
