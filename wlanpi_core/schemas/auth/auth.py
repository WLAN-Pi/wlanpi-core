"""Authentication and token schemas."""

from pydantic import BaseModel, Field, SecretStr


class KeyResponse(BaseModel):
    """Result of creating a signing key."""

    key_id: int
    message: str
    key: str | None = None


class TokenRequest(BaseModel):
    """Request body carrying a device ID."""

    device_id: str | None = Field(default=None, max_length=128)


class Token(BaseModel):
    """Issued JWT bearer token."""

    access_token: str = Field(description="JWT bearer token")
    token_type: str = Field(default="bearer", examples=["bearer"])


class TokenRevokeResponse(BaseModel):
    """Result of revoking a token."""

    status: str = Field(
        examples=["success", "info", "warning"],
        description="success | info (already revoked) | warning (not found)",
    )
    message: str = Field(examples=["Token revoked"])
    device_id: str | None = Field(
        default=None, description="Present when a token record was matched"
    )


# No control characters: PAM truncates at NUL and would check another account.
PAM_USERNAME_PATTERN = r"^[^\x00-\x1f\x7f]+$"


class PAMAuthRequest(BaseModel):
    """Credentials to verify against the system PAM stack."""

    username: str = Field(min_length=1, max_length=128, pattern=PAM_USERNAME_PATTERN)
    password: SecretStr = Field(min_length=1, max_length=512)


class PAMChangePasswordRequest(BaseModel):
    """Credentials to change an expired password through PAM."""

    username: str = Field(min_length=1, max_length=128, pattern=PAM_USERNAME_PATTERN)
    current_password: SecretStr = Field(min_length=1, max_length=512)
    new_password: SecretStr = Field(min_length=1, max_length=512)


class PAMAccountRequest(BaseModel):
    """Local account to check for a signed-in WebUI session."""

    username: str = Field(min_length=1, max_length=128, pattern=PAM_USERNAME_PATTERN)


class PAMAccountResponse(BaseModel):
    """Whether an account may still sign in, and a fingerprint of its password."""

    active: bool = Field(
        description="false when missing, not in sudo, locked or expired"
    )
    password_fingerprint: str | None = Field(
        examples=["3f9c0a1b2c4d5e6f"],
        description="Changes with every password change; null without a shadow entry",
    )


class PAMAuthResponse(BaseModel):
    """Outcome of a PAM verification or password-change attempt."""

    status: str = Field(
        examples=["success", "failure", "password_change_required"],
        description=(
            "success | failure | password_change_required | password_rejected"
        ),
    )
