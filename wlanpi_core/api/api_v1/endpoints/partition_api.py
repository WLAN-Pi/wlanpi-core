from datetime import datetime

from fastapi import APIRouter, Depends, Request, Response
from fastapi.responses import JSONResponse

from wlanpi_core.core.auth import verify_auth_wrapper
from wlanpi_core.core.logging import get_logger
from wlanpi_core.models.validation_error import ValidationError
from wlanpi_core.schemas.partitions.partitions import (
    BootInfo,
    LockStatus,
    OperationResult,
    PartitionInfo,
)
from wlanpi_core.services.partitions.device_service import DeviceService
from wlanpi_core.services.partitions.lock_service import LockService
from wlanpi_core.services.partitions.partition_service import PartitionService

log = get_logger(__name__)

router = APIRouter()


@router.middleware("http")
async def validate_device_middleware(request: Request, call_next):
    """
    Middleware to validate that the current device is a WLAN Pi Go model.
    Blocks partition management operations on non-Go devices.
    """
    device_service = DeviceService()
    if not device_service.is_allowed_device():
        error_msg = (
            device_service.get_compatibility_error() or "Unknown compatibility error"
        )
        return JSONResponse(
            status_code=403,
            content={
                "detail": f"Partition management is only available on select WLAN Pi devices: {error_msg}"
            },
        )
    return await call_next(request)


@router.get(
    "/info",
    response_model=PartitionInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_partition_info():
    """
    Returns information about the partition layout and current boot configuration.
    """
    try:
        partition_service = PartitionService()
        device_service = DeviceService()

        current_set = partition_service.get_current_partition_set()
        partition_service.get_inactive_partition_set()
        partition_paths = partition_service.get_device_paths()
        partition_uuids = partition_service.get_partition_uuids()

        boot_info = partition_service.get_boot_info()

        space_boot1 = partition_service.check_available_space(partition_paths["boot1"])
        space_boot2 = partition_service.check_available_space(partition_paths["boot2"])
        space_root1 = partition_service.check_available_space(partition_paths["root1"])
        space_root2 = partition_service.check_available_space(partition_paths["root2"])
        partition_service.check_available_space(partition_paths["home"])

        device_model = device_service.get_device_model()

        def format_size(size_bytes):
            if size_bytes < 1024:
                return f"{size_bytes} B"
            elif size_bytes < 1024 * 1024:
                return f"{size_bytes / 1024:.1f} KB"
            elif size_bytes < 1024 * 1024 * 1024:
                return f"{size_bytes / (1024 * 1024):.1f} MB"
            else:
                return f"{size_bytes / (1024 * 1024 * 1024):.1f} GB"

        set_a = {
            "set_name": "A",
            "boot_device": partition_paths["boot1"],
            "root_device": partition_paths["root1"],
            "boot_uuid": partition_uuids.get("boot1"),
            "root_uuid": partition_uuids.get("root1"),
            "is_active": current_set == "A",
            "is_default": boot_info.get("power_loss_boot") == "A",
            "available_space": {
                "boot": format_size(space_boot1),
                "root": format_size(space_root1),
            },
        }

        set_b = {
            "set_name": "B",
            "boot_device": partition_paths["boot2"],
            "root_device": partition_paths["root2"],
            "boot_uuid": partition_uuids.get("boot2"),
            "root_uuid": partition_uuids.get("root2"),
            "is_active": current_set == "B",
            "is_default": boot_info.get("power_loss_boot") == "B",
            "available_space": {
                "boot": format_size(space_boot2),
                "root": format_size(space_root2),
            },
        }

        return PartitionInfo(
            device_model=device_model,
            current_set=current_set,
            default_set=boot_info.get("power_loss_boot"),
            set_a=set_a,
            set_b=set_b,
            home_device=partition_paths["home"],
            home_uuid=partition_uuids.get("home"),
            on_power_loss_boot=boot_info.get("power_loss_boot"),
        )

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=True)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/boot-info",
    response_model=BootInfo,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_boot_info():
    """
    Returns detailed boot configuration information.
    """
    try:
        partition_service = PartitionService()
        boot_info = partition_service.get_boot_info()

        return BootInfo(**boot_info)

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=True)
        return Response(content="Internal Server Error", status_code=500)


@router.get(
    "/lock-status",
    response_model=LockStatus,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def get_lock_status():
    """
    Returns the current lock status for partition operations.
    """
    try:
        lock_service = LockService()
        lock_status = lock_service.get_lock_status()

        return LockStatus(
            locked=lock_status.get("locked", False),
            owner=lock_status.get("requester"),
            acquired_at=(
                datetime.fromisoformat(lock_status.get("acquired_at"))
                if lock_status.get("acquired_at")
                else None
            ),
            operation=lock_status.get("operation"),
            is_stale=lock_status.get("is_stale", False),
        )

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=True)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/release-lock",
    response_model=OperationResult,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def release_lock():
    """
    Forcibly releases a lock (use with caution).
    """
    try:
        lock_service = LockService()

        if not lock_service.is_locked():
            return OperationResult(success=True, message="No lock to release")

        lock_status = lock_service.get_lock_status()
        result = lock_service.force_release_lock()

        if result:
            return OperationResult(
                success=True,
                message="Lock released successfully",
                details={
                    "previous_owner": lock_status.get("requester", "Unknown"),
                    "previous_operation": lock_status.get("operation", "Unknown"),
                },
            )
        else:
            return OperationResult(success=False, message="Failed to release lock")

    except ValidationError as ve:
        return Response(content=ve.error_msg, status_code=ve.status_code)
    except Exception as ex:
        log.error(ex, exc_info=True)
        return Response(content="Internal Server Error", status_code=500)


@router.post(
    "/update",
    response_model=OperationResult,
    dependencies=[Depends(verify_auth_wrapper)],
)
async def update_partition(
    request: Request,
    image_file: UploadFile = File(...),
):
    """
    Update the inactive partition set with a new OS image.

    The image will be written to the currently inactive partition set.
    After updating, you can use the /tryboot endpoint to test the new partition.
    """
    try:
        with tempfile.NamedTemporaryFile(delete=False) as temp_file:
            image_path = temp_file.name

            try:
                content = await image_file.read()
                temp_file.write(content)
                temp_file.flush()
            except Exception as e:
                log.error(f"Error saving uploaded file: {e}", exc_info=True)
                raise HTTPException(
                    status_code=500, detail="Failed to process uploaded image"
                )

        lock_service = LockService()

        if lock_service.is_locked() and not lock_service.is_lock_stale():
            raise HTTPException(
                status_code=409, detail="Another update operation is in progress"
            )

        if not lock_service.acquire_lock("update", "api"):
            raise HTTPException(
                status_code=409, detail="Could not acquire lock for update operation"
            )

        try:
            partition_service = PartitionService()
            config_service = ConfigService()
            image_handler = ImageHandler()

            update_manager = UpdateManager(
                lock_service, partition_service, config_service, image_handler
            )

            prepare_result = await update_manager.prepare_update(image_path)
            if not prepare_result["success"]:
                raise HTTPException(status_code=400, detail=prepare_result["message"])

            # Execute update (potentially a long-running operation)
            # In a production environment, this should be a background task
            await update_manager.execute_update(image_path)

            inactive_set = partition_service.get_inactive_partition_set()

            return OperationResult(
                success=True,
                message=f"Successfully updated partition set {inactive_set}",
                details={
                    "target_set": inactive_set,
                    "next_steps": "Use the /tryboot endpoint to test the new partition",
                },
            )

        finally:
            lock_service.release_lock()

            try:
                os.unlink(image_path)
            except Exception as e:
                log.error(f"Error cleaning up temporary file: {e}")

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Error updating partition: {e}", exc_info=True)
        raise HTTPException(
            status_code=500, detail=f"Failed to update partition: {str(e)}"
        )
