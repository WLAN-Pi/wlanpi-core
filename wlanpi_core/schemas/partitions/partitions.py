from datetime import datetime
from typing import Dict, Literal, Optional

from pydantic import BaseModel, Field


class PartitionSet(BaseModel):
    """Represents a partition set (A or B)"""

    set_name: Literal["A", "B"] = Field(description="Partition set name")
    boot_device: str = Field(description="Boot partition device path")
    root_device: str = Field(description="Root partition device path")
    boot_uuid: Optional[str] = Field(None, description="Boot partition UUID")
    root_uuid: Optional[str] = Field(None, description="Root partition UUID")
    is_active: bool = Field(description="Whether this set is currently active")
    is_default: bool = Field(description="Whether this set is the default boot option")
    available_space: Optional[Dict[str, str]] = Field(
        None, description="Available space information"
    )


class PartitionInfo(BaseModel):
    """Information about the partition layout and status"""

    device_model: str = Field(description="Device model")
    current_set: str = Field(description="Currently active partition set")
    default_set: Optional[str] = Field(None, description="Default boot partition set")
    set_a: PartitionSet = Field(description="Partition set A details")
    set_b: PartitionSet = Field(description="Partition set B details")
    home_device: str = Field(description="Home partition device path")
    home_uuid: Optional[str] = Field(None, description="Home partition UUID")
    on_power_loss_boot: Optional[str] = Field(
        None, description="Which partition set will boot after power loss"
    )


class BootInfo(BaseModel):
    """Detailed boot configuration information"""

    system_info: str = Field(description="System information from uname")
    model: str = Field(description="Device model information")
    current_boot_dev: str = Field(description="Current boot partition")
    current_root_dev: str = Field(description="Current root partition")
    current_home_dev: Optional[str] = Field(None, description="Current home partition")
    current_set: str = Field(description="Current partition set")
    cmdline_txt: str = Field(description="Current cmdline.txt contents")
    cmdline_b_txt: Optional[str] = Field(
        None, description="cmdline-b.txt contents if exists"
    )
    tryboot_txt: Optional[str] = Field(
        None, description="tryboot.txt contents if exists"
    )
    autoboot_txt: Optional[str] = Field(
        None, description="Current autoboot.txt contents"
    )
    boot1_autoboot_txt: Optional[str] = Field(
        None, description="Boot partition 1 autoboot.txt contents"
    )
    boot1_partition: Optional[str] = Field(
        None, description="Boot partition setting in boot1 autoboot.txt"
    )
    power_loss_boot: str = Field(
        description="Partition set that will boot after power loss"
    )
    partition_layout: str = Field(description="Partition layout information")
    partition_usage: Optional[str] = Field(
        None, description="Partition usage statistics"
    )
    kernel_cmdline: str = Field(description="Kernel command line used")
    boot_history: Optional[str] = Field(None, description="Recent boot history")


class UpdateStatus(BaseModel):
    """Status of an update operation"""

    in_progress: bool = Field(description="Whether an update is currently in progress")
    operation: Optional[str] = Field(
        None, description="Current operation if in progress"
    )
    progress_percent: Optional[int] = Field(None, description="Progress percentage")
    current_step: Optional[str] = Field(
        None, description="Current step in the update process"
    )
    started_at: Optional[datetime] = Field(None, description="When the update started")
    estimated_completion: Optional[datetime] = Field(
        None, description="Estimated completion time"
    )
    target_set: Optional[str] = Field(None, description="Target partition set")


class OperationResult(BaseModel):
    """Result of a partition operation"""

    success: bool = Field(description="Whether the operation was successful")
    message: str = Field(description="Operation result message")
    details: Optional[Dict[str, str]] = Field(None, description="Additional details")


class LockStatus(BaseModel):
    """Status of the update lock"""

    locked: bool = Field(
        description="Whether the system is currently locked for updates"
    )
    owner: Optional[str] = Field(None, description="Process or user holding the lock")
    acquired_at: Optional[datetime] = Field(
        None, description="When the lock was acquired"
    )
    operation: Optional[str] = Field(
        None, description="Operation that acquired the lock"
    )
    is_stale: Optional[bool] = Field(
        None, description="Whether the lock appears to be stale"
    )
