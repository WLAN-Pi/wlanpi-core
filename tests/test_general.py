import time
import unittest.mock
from unittest.mock import Mock, patch

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils import general
from wlanpi_core.utils.general import get_model_info


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

    @patch("wlanpi_core.utils.general.run_command")
    def test_get_model_info(self, mock_run_command):
        mock_output = """
        Model:                WLAN Pi R4
        Main board:           Raspberry Pi 4
        USB Wi-Fi adapter:    3574:6211 MediaTek Inc. Wireless_Device
        Bluetooth adapter:    Built-in
        """

        mock_run_command.return_value.stdout = mock_output

        expected_dict = {
            "Model": "WLAN Pi R4",
            "Main board": "Raspberry Pi 4",
            "USB Wi-Fi adapter": "3574:6211 MediaTek Inc. Wireless_Device",
            "Bluetooth adapter": "Built-in",
        }

        result = get_model_info()

        self.assertEqual(result, expected_dict)

    @patch("wlanpi_core.utils.general.run_command")
    def test_get_model_info_error(self, mock_run_command):
        mock_output = "Error: Command not found"

        mock_run_command.return_value.stdout = mock_output
        mock_run_command.return_value.return_code = 1
        mock_run_command.side_effect = RunCommandError("Failed to run command", 1)

        with self.assertRaises(RunCommandError):
            get_model_info()


if __name__ == "__main__":
    unittest.main()
