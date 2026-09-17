"""Request/response models for the internal PAM authentication endpoint."""

from pydantic import BaseModel, Field, SecretStr


class PAMAuthRequest(BaseModel):
    """Credentials to verify against the system PAM stack."""

    username: str = Field(min_length=1, max_length=128)
    password: SecretStr = Field(min_length=1, max_length=512)


class PAMAuthResponse(BaseModel):
    """Outcome of a PAM verification attempt."""

    status: str = Field(
        examples=["success", "failure", "password_change_required"],
        description="success | failure | password_change_required",
    )
