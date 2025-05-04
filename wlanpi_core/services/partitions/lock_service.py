import json
import os
from datetime import datetime, timedelta
from typing import Dict

from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class LockService:
    """
    Manages locking for partition operations to prevent concurrent updates.

    Uses file-based locking stored in the persistent storage location.
    """

    LOCK_FILE = "/home/wlanpi/.local/share/wlanpi-core/partition_lock.json"

    LOCK_TIMEOUT = 1800

    def __init__(self):
        """Initialize the lock manager."""
        self._ensure_directory()

    def _ensure_directory(self) -> None:
        """Ensure the directory for the lock file exists."""
        lock_dir = os.path.dirname(self.LOCK_FILE)
        os.makedirs(lock_dir, mode=0o755, exist_ok=True)

    def acquire_lock(self, operation: str, requester: str) -> bool:
        """
        Try to acquire the lock for a partition operation.

        Args:
            operation: Description of the operation
            requester: Identifier for who is requesting the lock

        Returns:
            bool: True if lock was acquired, False otherwise
        """
        try:
            if self.is_locked() and not self.is_lock_stale():
                log.warning(
                    f"Lock acquisition failed: another operation is in progress"
                )
                return False

            lock_data = {
                "operation": operation,
                "requester": requester,
                "pid": os.getpid(),
                "acquired_at": datetime.now().isoformat(),
                "hostname": os.uname().nodename,
            }

            with open(self.LOCK_FILE, "w") as f:
                json.dump(lock_data, f)

            log.info(f"Lock acquired for operation: {operation}")
            return True

        except Exception as e:
            log.error(f"Error acquiring lock: {e}", exc_info=True)
            return False

    def release_lock(self) -> bool:
        """
        Release the current lock.

        Returns:
            bool: True if successful, False otherwise
        """
        try:
            if os.path.exists(self.LOCK_FILE):
                os.unlink(self.LOCK_FILE)
                log.info("Lock released")
            return True

        except Exception as e:
            log.error(f"Error releasing lock: {e}", exc_info=True)
            return False

    def get_lock_status(self) -> Dict:
        """
        Check if lock exists and get details.

        Returns:
            Dict: Lock status and details
        """
        if not os.path.exists(self.LOCK_FILE):
            return {"locked": False}

        try:
            with open(self.LOCK_FILE, "r") as f:
                lock_data = json.load(f)

            lock_data["locked"] = True
            lock_data["is_stale"] = self._check_stale_lock(lock_data)

            return lock_data

        except Exception as e:
            log.error(f"Error reading lock file: {e}", exc_info=True)
            return {"locked": True, "error": str(e), "is_stale": True}

    def is_locked(self) -> bool:
        """
        Check if a lock exists.

        Returns:
            bool: True if locked, False otherwise
        """
        return os.path.exists(self.LOCK_FILE)

    def is_lock_stale(self) -> bool:
        """
        Check if existing lock is stale.

        Returns:
            bool: True if lock is stale, False otherwise
        """
        lock_data = self.get_lock_status()
        if not lock_data.get("locked", False):
            return False

        return self._check_stale_lock(lock_data)

    def _check_stale_lock(self, lock_data: Dict) -> bool:
        """
        Check if a lock is stale based on its data.

        Args:
            lock_data: Lock data dictionary

        Returns:
            bool: True if lock is stale, False otherwise
        """
        pid = lock_data.get("pid")
        if pid:
            try:
                os.kill(pid, 0)
            except OSError:
                return True

        try:
            acquired_at = datetime.fromisoformat(lock_data.get("acquired_at", ""))
            time_diff = datetime.now() - acquired_at
            if time_diff > timedelta(seconds=self.LOCK_TIMEOUT):
                return True
        except Exception:
            return True

        return False

    def force_release_lock(self) -> bool:
        """
        Force release a lock, even if it's not stale.
        Use with caution!

        Returns:
            bool: True if successful, False otherwise
        """
        return self.release_lock()
