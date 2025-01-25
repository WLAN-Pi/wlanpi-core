from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from wlanpi_core.core.database import Base


class SigningKey(Base):
    """
    Model representing cryptographic signing keys

    Stores encrypted keys used for token signing and verification
    """

    __tablename__ = "signing_keys"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    updated_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), onupdate=func.now(), nullable=True
    )
    tokens: Mapped[List[Token]] = relationship(
        "Token", back_populates="signing_key", cascade="all, delete-orphan"
    )


class Token(Base):
    """
    Model representing authentication tokens

    Stores token details, associated device, and signing key
    """

    __tablename__ = "tokens"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    token: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    revoked: Mapped[bool] = mapped_column(Boolean, default=False)

    key_id: Mapped[int] = mapped_column(ForeignKey("signing_keys.id"), nullable=False)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"), nullable=False
    )

    signing_key: Mapped[SigningKey] = relationship(
        "SigningKey", back_populates="tokens"
    )
    device: Mapped[APIDevice] = relationship("APIDevice", back_populates="tokens")


class APIDevice(Base):
    """
    Model representing devices interacting with the system

    Tracks device first seen and last seen timestamps
    """

    __tablename__ = "devices"

    device_id: Mapped[str] = mapped_column(String, primary_key=True)
    first_seen: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )
    last_seen: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    tokens: Mapped[List[Token]] = relationship(
        "Token", back_populates="device", cascade="all, delete-orphan"
    )
    stats: Mapped[Optional[APIDeviceStats]] = relationship(
        "APIDeviceStats",
        back_populates="device",
        uselist=False,
        cascade="all, delete-orphan",
    )
    activities: Mapped[List[APIDeviceActivity]] = relationship(
        "APIDeviceActivity", back_populates="device", cascade="all, delete-orphan"
    )


class APIDeviceActivity(Base):
    """
    Model for tracking device activities and API interactions
    """

    __tablename__ = "device_activity"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)

    device: Mapped[APIDevice] = relationship("APIDevice", back_populates="activities")


class APIDeviceActivityRecent(Base):
    """
    Model for recent device activities with short-term retention
    """

    __tablename__ = "device_activity_recent"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"), nullable=False
    )
    endpoint: Mapped[str] = mapped_column(String, nullable=False)
    status_code: Mapped[int] = mapped_column(Integer, nullable=False)

    # Optional: Add relationship if needed
    # device: Mapped[Device] = relationship("Device")


class APIDeviceStats(Base):
    """
    Model for tracking device-level statistics
    """

    __tablename__ = "device_stats"

    device_id: Mapped[str] = mapped_column(
        ForeignKey("devices.device_id"), primary_key=True
    )
    request_count: Mapped[int] = mapped_column(Integer, default=0)
    error_count: Mapped[int] = mapped_column(Integer, default=0)
    endpoint_count: Mapped[int] = mapped_column(Integer, default=0)
    last_activity: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    device: Mapped[APIDevice] = relationship("APIDevice", back_populates="stats")
