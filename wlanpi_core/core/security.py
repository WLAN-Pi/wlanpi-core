import grp
import os
import pwd
import secrets
import time
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

from wlanpi_core.constants import ENCRYPTION_KEY_FILE, SECRETS_DIR, SHARED_SECRET_FILE
from wlanpi_core.core.logging import get_logger

log = get_logger(__name__)


class SecurityInitError(Exception):
    pass


class SecurityManager:
    def __init__(self):
        self.secrets_path = Path(SECRETS_DIR)
        self._fernet: Optional[Fernet] = None
        try:
            # Wait for filesystem to be ready before proceeding
            if not self._wait_for_filesystem_ready():
                raise SecurityInitError("Filesystem not ready after maximum retries")
            
            self._setup_secrets_directory()
            self.shared_secret = self._setup_shared_secret()
            self._setup_encryption_key()
            log.debug("Security initialization complete")
        except Exception as e:
            log.exception(f"Security initialization failed: {e}")
            raise SecurityInitError(f"Failed to initialize security: {e}")

    def _wait_for_filesystem_ready(self, max_retries: int = 5, retry_delay: float = 2.0) -> bool:
        """Wait for filesystem to be ready for write operations"""
        for attempt in range(max_retries):
            try:
                self.secrets_path.mkdir(mode=0o700, parents=True, exist_ok=True)
                
                # Verify we can stat the directory
                stat_info = self.secrets_path.stat()
                
                # Check if we can write to the directory
                test_file = self.secrets_path / f".test_{os.getpid()}_{attempt}"
                try:
                    test_data = os.urandom(16)
                    test_file.write_bytes(test_data)
                    read_data = test_file.read_bytes()
                    
                    # Always try to clean up, even if the test fails
                    try:
                        test_file.unlink()
                    except:
                        pass
                    
                    if read_data == test_data:
                        log.debug(f"Filesystem ready after {attempt + 1} attempts")
                        return True
                except Exception as e:
                    # Always try to clean up on failure
                    try:
                        if test_file.exists():
                            test_file.unlink()
                    except:
                        pass
                    log.debug(f"Write test failed: {e}")
                
                if attempt < max_retries - 1:
                    log.warning(f"Filesystem not ready, attempt {attempt + 1}/{max_retries}, waiting {retry_delay}s")
                    time.sleep(retry_delay)
                    
            except Exception as e:
                log.debug(f"Filesystem check failed: {e}")
                if attempt < max_retries - 1:
                    time.sleep(retry_delay)
        
        log.error("Filesystem not ready after all retries")
        return False
    
    def _setup_secrets_directory(self):
        """Create and secure secrets directory"""
        try:
            self.secrets_path.mkdir(mode=0o700, parents=True, exist_ok=True)
        except Exception as e:
            log.exception(f"Failed to create secrets directory: {e}")
            raise

    def _setup_shared_secret(self) -> bytes:
        """Generate or load HMAC shared secret"""
        secret_path = self.secrets_path / SHARED_SECRET_FILE
        secrets_dir = self.secrets_path

        try:
            dir_stat = secrets_dir.stat()
            dir_gid = grp.getgrnam("wlanpi").gr_gid

            if dir_stat.st_gid != dir_gid or dir_stat.st_mode & 0o777 != 0o710:
                os.chown(str(secrets_dir), 0, dir_gid)  # root:wlanpi
                secrets_dir.chmod(0o710)  # rwx--x---
                log.debug("Updated secrets directory permissions")

            if not secret_path.exists():
                secret = secrets.token_bytes(32)
                secret_path.write_bytes(secret)
                # Set file ownership to root:wlanpi
                uid = pwd.getpwnam("root").pw_uid
                gid = grp.getgrnam("wlanpi").gr_gid
                os.chown(str(secret_path), uid, gid)
                # Set permissions to 0o640 - readable by owner (root) and group (wlanpi)
                secret_path.chmod(0o640)
                log.debug("Generated new shared secret")
            else:
                stat = secret_path.stat()
                uid = pwd.getpwnam("root").pw_uid
                gid = grp.getgrnam("wlanpi").gr_gid
                if stat.st_uid != uid or stat.st_gid != gid:
                    os.chown(str(secret_path), uid, gid)
                    log.debug("Updated secret file ownership to root:wlanpi")
                if stat.st_mode & 0o777 != 0o640:
                    secret_path.chmod(0o640)
                    log.debug("Updated secret file permissions to 0o640")
                secret = secret_path.read_bytes()
                if not secret:
                    # File exists but is empty - regenerate it
                    log.warning("Shared secret file is empty, regenerating...")
                    secret = secrets.token_bytes(32)
                    secret_path.write_bytes(secret)
                    os.chown(str(secret_path), uid, gid)
                    secret_path.chmod(0o640)
                    log.debug("Regenerated shared secret")
                else:
                    log.debug("Loaded existing shared secret")

            return secret

        except Exception as e:
            log.exception(f"Failed to setup shared secret: {e}")
            raise

    def _setup_encryption_key(self):
        """Generate or load Fernet encryption key"""
        key_path = self.secrets_path / ENCRYPTION_KEY_FILE

        try:
            if not key_path.exists():
                key = Fernet.generate_key()
                key_path.write_bytes(key)
                key_path.chmod(0o600)
                log.debug("Generated new encryption key")
            else:
                key = key_path.read_bytes()
                if not key:
                    # File exists but is empty - regenerate it
                    log.warning("Encryption key file is empty, regenerating...")
                    key = Fernet.generate_key()
                    key_path.write_bytes(key)
                    key_path.chmod(0o600)
                    log.debug("Regenerated encryption key")
                else:
                    # Validate the key is a valid Fernet key
                    try:
                        test_fernet = Fernet(key)
                        # Quick validation
                        test_fernet.decrypt(test_fernet.encrypt(b"test"))
                        log.debug("Loaded existing encryption key")
                    except Exception:
                        # Key is corrupted - regenerate it
                        log.warning("Encryption key file is corrupted, regenerating...")
                        key = Fernet.generate_key()
                        key_path.write_bytes(key)
                        key_path.chmod(0o600)
                        log.debug("Regenerated encryption key")

            self._fernet = Fernet(key)

        except Exception as e:
            log.exception(f"Failed to setup encryption key: {e}")
            raise

    @property
    def fernet(self) -> Fernet:
        """Get initialized Fernet instance"""
        if not self._fernet:
            raise SecurityInitError("Fernet not initialized")
        return self._fernet

    def encrypt(self, data: bytes) -> bytes:
        """Encrypt data using Fernet"""
        return self.fernet.encrypt(data)

    def decrypt(self, data: bytes) -> bytes:
        """Decrypt data using Fernet"""
        return self.fernet.decrypt(data)
