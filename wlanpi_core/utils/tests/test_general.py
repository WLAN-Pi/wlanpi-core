import time
import unittest.mock  # python -m unittest.mock
from unittest.mock import patch, Mock

from wlanpi_core.models.runcommand_error import RunCommandError
from wlanpi_core.utils import general
from wlanpi_core.utils.general import get_model_info


class TestGeneralUtils(unittest.TestCase):

    @unittest.mock.patch('wlanpi_core.utils.general.run_command')
    def test_get_hostname(self, mock_run_command):
        # Mock the run_command function to return a mocked subprocess object with specific attributes
        mock_subprocess = unittest.mock.Mock()
        mock_subprocess.stdout = 'test_hostname\n'  # Replace this with your expected hostname
        mock_run_command.return_value = mock_subprocess

        result = general.get_hostname()

        # Assert that the function called run_command correctly
        mock_run_command.assert_called_once_with(['hostname'])
        # Assert that the hostname is returned properly
        self.assertEqual(result, 'test_hostname')


    def test_get_current_unix_timestamp(self):
        # Get current Unix timestamp in milliseconds
        ms = int(round(time.time() * 1000))

        # Call function and get its result
        func_ms = general.get_current_unix_timestamp()

        # The difference should be less than a second (assuming the test is not run at the exact second)
        self.assertTrue(abs(func_ms - ms) < 1000,
                        f"The function returned {func_ms}, which differs from current Unix timestamp in milliseconds by more than 1000.")


    @patch('wlanpi_core.utils.general.run_command')
    def test_get_uptime(self, mock_run_command: Mock):
        # Define the output from the 'jc uptime' command
        expected_output = {"uptime": "123456", "idle_time": "7890"}

        # Configure the mock to return this output when called with 'jc uptime'.
        mock_run_command.return_value.output_from_json.return_value = expected_output

        actual_output = general.get_uptime()

        self.assertEqual(actual_output, expected_output)



    @patch('wlanpi_core.utils.general.run_command')
    def test_get_model_info(self, mock_run_command):
        # Define the output of run_command that we expect to get from wlanpi-model command
        mock_output = """
        Model:                WLAN Pi R4
        Main board:           Raspberry Pi 4
        USB Wi-Fi adapter:    3574:6211 MediaTek Inc. Wireless_Device
        Bluetooth adapter:    Built-in
        """

        # Set up the mock object's return value. This is where we tell it what to do when called
        mock_run_command.return_value.stdout = mock_output

        expected_dict = {
            "Model": "WLAN Pi R4",
            "Main board": "Raspberry Pi 4",
            "USB Wi-Fi adapter": "3574:6211 MediaTek Inc. Wireless_Device",
            "Bluetooth adapter": "Built-in",
        }

        # Call the function we are testing and store its return value in a variable
        result = get_model_info()

        # Assert that the return value is what we expect it to be, i.e., equal to expected_dict
        self.assertEqual(result, expected_dict)


    @patch('wlanpi_core.utils.general.run_command')
    def test_get_model_info_error(self, mock_run_command):
        # Define the output of run_command that we expect to get from wlanpi-model command when error occurs
        mock_output = "Error: Command not found"

        # Set up the mock object's return value. This is where we tell it what to do when called
        mock_run_command.return_value.stdout = mock_output
        mock_run_command.return_value.return_code = 1
        mock_run_command.side_effect = RunCommandError("Failed to run command",1)

        # Assert that the function raises a RunCommandError when there is an error running the command
        with self.assertRaises(RunCommandError):
            get_model_info()

if __name__ == '__main__':
    unittest.main()
