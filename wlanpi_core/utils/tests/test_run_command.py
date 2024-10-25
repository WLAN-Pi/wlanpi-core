import unittest
from unittest.mock import patch
from io import StringIO
from wlanpi_core.utils.general import run_command, RunCommandError, CommandResult

class TestRunCommand(unittest.TestCase):

    def test_run_command_success(self):
        # Test a successful command execution
        result = run_command(["echo", "test"])
        self.assertEqual(result.stdout, "test\n")
        self.assertEqual(result.stderr, "")
        self.assertEqual(result.return_code, 0)

    def test_run_command_failure(self):
        # Test a failing command execution with raise_on_fail=True
        with self.assertRaises(RunCommandError) as context:
            run_command(["ls", "nonexistent_file"])
        self.assertIn("No such file or directory", str(context.exception))

    def test_run_command_failure_no_raise(self):
        # Test a failing command execution with raise_on_fail=False
        result = run_command(["false"], raise_on_fail=False)
        self.assertEqual(result.return_code, 1)

    def test_run_command_input(self):
        # Test providing input to the command
        result = run_command(["cat"], input="test input")
        self.assertEqual(result.stdout, "test input")

    @patch('subprocess.run')
    def test_run_command_stdin(self, mock_run):
        # Test providing stdin to the command
        mock_run.return_value.stdout = "test input"
        mock_run.return_value.stderr = ""
        mock_run.return_value.return_code = 0
        result = run_command(["cat"], stdin=StringIO("test input"))
        self.assertEqual(result.stdout, "test input")

    def test_run_command_input_and_stdin_error(self):
        # Test raising an error when both input and stdin are provided
        with self.assertRaises(RunCommandError) as context:
            run_command(["echo"], input="test", stdin=StringIO("test"))
        self.assertIn("You cannot use both 'input' and 'stdin'", str(context.exception))

    def test_run_command_shell_warning(self):
        # Test the warning message when using shell=True
        with self.assertLogs(level='WARNING') as cm:
            run_command("echo test", shell=True)
        self.assertIn("Command echo test being run as a shell script", cm.output[0])

    def test_command_result(self):
        # Test the CommandResult class
        result = CommandResult("output", "error", 0)
        self.assertEqual(result.stdout, "output")
        self.assertEqual(result.stderr, "error")
        self.assertEqual(result.return_code, 0)


if __name__ == '__main__':
    unittest.main()
