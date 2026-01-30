"""
Tests for namespace lifecycle operations.
"""
import pytest
from unittest.mock import Mock, patch

from wlanpi_core.models.command_result import CommandResult
from wlanpi_core.models.network.namespace.namespace_errors import (
    NetworkNamespaceError,
    NetworkNamespaceNotFoundError,
)
from wlanpi_core.namespaces.namespace import (
    create_namespace,
    delete_namespace,
    list_namespaces,
    namespace_exists,
)


class TestCreateNamespace:
    """Tests for create_namespace function."""

    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_create_namespace_success(self, mock_run_command):
        """Test successful namespace creation."""
        mock_run_command.return_value = CommandResult("", "", 0)

        result = create_namespace("test_ns")

        mock_run_command.assert_called_once_with(
            ["sudo", "ip", "netns", "add", "test_ns"],
            raise_on_fail=True,
        )
        assert result.return_code == 0

    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_create_namespace_without_sudo(self, mock_run_command):
        """Test namespace creation without sudo."""
        mock_run_command.return_value = CommandResult("", "", 0)

        result = create_namespace("test_ns", use_sudo=False)

        mock_run_command.assert_called_once_with(
            ["ip", "netns", "add", "test_ns"],
            raise_on_fail=True,
        )
        assert result.return_code == 0

    def test_create_namespace_empty_name(self):
        """Test that empty namespace name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            create_namespace("")

        assert "cannot be empty" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_create_namespace_failure(self, mock_run_command):
        """Test namespace creation failure."""
        mock_run_command.side_effect = Exception("Command failed")

        with pytest.raises(NetworkNamespaceError) as exc_info:
            create_namespace("test_ns")

        assert "Failed to create namespace" in str(exc_info.value)


class TestDeleteNamespace:
    """Tests for delete_namespace function."""

    @patch("wlanpi_core.namespaces.namespace.namespace_exists")
    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_delete_namespace_success(self, mock_run_command, mock_exists):
        """Test successful namespace deletion."""
        mock_exists.return_value = True
        mock_run_command.return_value = CommandResult("", "", 0)

        result = delete_namespace("test_ns")

        mock_run_command.assert_called_once_with(
            ["sudo", "ip", "netns", "delete", "test_ns"],
            raise_on_fail=True,
        )
        assert result.return_code == 0

    @patch("wlanpi_core.namespaces.namespace.namespace_exists")
    def test_delete_namespace_not_found(self, mock_exists):
        """Test deletion of non-existent namespace."""
        mock_exists.return_value = False

        with pytest.raises(NetworkNamespaceNotFoundError) as exc_info:
            delete_namespace("test_ns")

        assert "does not exist" in str(exc_info.value)

    @patch("wlanpi_core.namespaces.namespace.namespace_exists")
    def test_delete_namespace_not_found_no_raise(self, mock_exists):
        """Test deletion of non-existent namespace with raise_on_fail=False."""
        mock_exists.return_value = False

        result = delete_namespace("test_ns", raise_on_fail=False)

        assert result.return_code == 1
        assert "does not exist" in result.stderr

    def test_delete_namespace_empty_name(self):
        """Test that empty namespace name raises ValueError."""
        with pytest.raises(ValueError) as exc_info:
            delete_namespace("")

        assert "cannot be empty" in str(exc_info.value)


class TestListNamespaces:
    """Tests for list_namespaces function."""

    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_list_namespaces_success(self, mock_run_command):
        """Test successful namespace listing."""
        mock_run_command.return_value = CommandResult(
            "test_ns (id: 0)\nother_ns (id: 1)\n", "", 0
        )

        namespaces = list_namespaces()

        mock_run_command.assert_called_once_with(
            ["ip", "netns", "list"],
            raise_on_fail=False,
        )
        assert "test_ns" in namespaces
        assert "other_ns" in namespaces
        assert len(namespaces) == 2

    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_list_namespaces_empty(self, mock_run_command):
        """Test listing when no namespaces exist."""
        mock_run_command.return_value = CommandResult("", "", 0)

        namespaces = list_namespaces()

        assert namespaces == []

    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_list_namespaces_with_json(self, mock_run_command):
        """Test namespace listing with JSON output."""
        mock_result = Mock()
        mock_result.return_code = 0
        mock_result.output_from_json.return_value = [
            {"name": "test_ns", "id": 0},
            {"name": "other_ns", "id": 1},
        ]
        mock_run_command.return_value = mock_result

        namespaces = list_namespaces(use_json=True)

        mock_run_command.assert_called_once_with(
            ["ip", "-j", "netns", "list"],
            raise_on_fail=False,
        )
        assert len(namespaces) == 2
        assert namespaces[0]["name"] == "test_ns"

    @patch("wlanpi_core.namespaces.namespace.run_command")
    def test_list_namespaces_failure(self, mock_run_command):
        """Test namespace listing failure."""
        mock_run_command.return_value = CommandResult("", "error", 1)

        with pytest.raises(NetworkNamespaceError) as exc_info:
            list_namespaces()

        assert "Error listing namespaces" in str(exc_info.value)


class TestNamespaceExists:
    """Tests for namespace_exists function."""

    @patch("wlanpi_core.namespaces.namespace.list_namespaces")
    def test_namespace_exists_true(self, mock_list):
        """Test that existing namespace returns True."""
        mock_list.return_value = ["test_ns", "other_ns"]

        assert namespace_exists("test_ns") is True

    @patch("wlanpi_core.namespaces.namespace.list_namespaces")
    def test_namespace_exists_false(self, mock_list):
        """Test that non-existent namespace returns False."""
        mock_list.return_value = ["test_ns", "other_ns"]

        assert namespace_exists("nonexistent") is False

    @patch("wlanpi_core.namespaces.namespace.list_namespaces")
    def test_namespace_exists_empty_list(self, mock_list):
        """Test namespace_exists with empty namespace list."""
        mock_list.return_value = []

        assert namespace_exists("test_ns") is False

    def test_namespace_exists_empty_name(self):
        """Test that empty namespace name returns False."""
        assert namespace_exists("") is False

    @patch("wlanpi_core.namespaces.namespace.list_namespaces")
    def test_namespace_exists_handles_error(self, mock_list):
        """Test that namespace_exists handles listing errors gracefully."""
        mock_list.side_effect = NetworkNamespaceError("Listing failed")

        # Should return False on error
        assert namespace_exists("test_ns") is False
