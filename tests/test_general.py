import time
import unittest.mock
from unittest.mock import Mock, patch

from wlanpi_core.utils import general


class TestGeneralUtils(unittest.TestCase):
    @unittest.mock.patch("wlanpi_core.utils.general.run_command")
    def test_get_hostname(self, mock_run_command):
        mock_subprocess = unittest.mock.Mock()
        mock_subprocess.stdout = "test_hostname\n"
        mock_run_command.return_value = mock_subprocess

        result = general.get_hostname()

        mock_run_command.assert_called_once_with(["hostname"])
        self.assertEqual(result, "test_hostname")

    def test_get_current_unix_timestamp(self):
        ms = round(time.time() * 1000)

        func_ms = general.get_current_unix_timestamp()

        self.assertTrue(
            abs(func_ms - ms) < 1000,
            f"The function returned {func_ms}, which differs from current Unix timestamp in milliseconds by more than 1000.",
        )

    @patch("wlanpi_core.utils.general.run_command")
    def test_get_uptime(self, mock_run_command: Mock):
        expected_output = {"uptime": "123456", "idle_time": "7890"}

        mock_run_command.return_value.output_from_json.return_value = expected_output

        actual_output = general.get_uptime()

        self.assertEqual(actual_output, expected_output)


if __name__ == "__main__":
    unittest.main()
