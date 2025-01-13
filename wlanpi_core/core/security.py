import logging
import secrets
from pathlib import Path
from typing import Optional

from cryptography.fernet import Fernet

log = logging.getLogger("uvicorn")

class SecurityInitError(Exception):
    pass

class SecurityManager:
    SECRETS_DIR = "/opt/wlanpi-core/.secrets"
    ENCRYPTION_KEY_FILE = "encryption.key"
    SHARED_SECRET_FILE = "shared_secret"
    
    def __init__(self):
        self.secrets_path = Path(self.SECRETS_DIR)
        self._fernet: Optional[Fernet] = None
        try:
            self._setup_secrets_directory()
            self.shared_secret = self._setup_shared_secret()
            self._setup_encryption_key()
            log.info("Security initialization complete")
        except Exception as e:
            log.exception(f"Security initialization failed: {e}")
            raise SecurityInitError(f"Failed to initialize security: {e}")

    def _setup_secrets_directory(self):
        """Create and secure secrets directory"""
        try:
            self.secrets_path.mkdir(mode=0o700, parents=True, exist_ok=True)
            log.debug(f"Secured secrets directory: {self.SECRETS_DIR}")
        except Exception as e:
            log.exception(f"Failed to create secrets directory: {e}")
            raise
            
    def _setup_shared_secret(self) -> bytes:
        """Generate or load HMAC shared secret"""
        secret_path = self.secrets_path / self.SHARED_SECRET_FILE
        
        try:
            if not secret_path.exists():
                secret = secrets.token_bytes(32)
                secret_path.write_bytes(secret)
                secret_path.chmod(0o600)
                log.info("Generated new shared secret")
            else:
                secret = secret_path.read_bytes()
                if not secret:
                    raise ValueError("Empty shared secret file")
                log.info("Loaded existing shared secret")
                
            return secret
            
        except Exception as e:
            log.exception(f"Failed to setup shared secret: {e}")
            raise

    def _setup_encryption_key(self):
        """Generate or load Fernet encryption key"""
        key_path = self.secrets_path / self.ENCRYPTION_KEY_FILE
        
        try:
            if not key_path.exists():
                key = Fernet.generate_key()
                key_path.write_bytes(key)
                key_path.chmod(0o600)
                log.info("Generated new encryption key")
            else:
                key = key_path.read_bytes()
                if not key:
                    raise ValueError("Empty encryption key file")
                log.info("Loaded existing encryption key")

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