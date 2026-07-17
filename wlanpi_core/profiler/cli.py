import asyncio
from asyncio.subprocess import Process
from typing import Optional

import wlanpi_core.profiler.models as models
from wlanpi_core.core.logging import get_logger
from wlanpi_core.utils.general import terminate_process_async

log = get_logger(__name__)
profiler_process: Optional[Process] = None
_profiler_lock = asyncio.Lock()


async def start_profiler(args: models.Start):
    global profiler_process

    cmd = ["profiler"]
    value_options = {
        "-c": args.channel,
        "-f": args.frequency,
        "-i": args.interface,
        "-s": args.ssid,
    }
    for flag, value in value_options.items():
        if value:
            cmd += [flag, str(value)]

    bool_flags = [
        ("--debug", args.debug),
        ("--noprep", args.noprep),
        ("--noAP", args.noAP),
        ("--no11r", args.no11r),
        ("--no11ax", args.no11ax),
        ("--no11be", args.no11be),
        ("--noprofilertlv", args.noprofilertlv),
        ("--wpa3_personal_transition", args.wpa3_personal_transition),
        ("--wpa3_personal", args.wpa3_personal),
        ("--oui_update", args.oui_update),
        ("--no_bpf_filters", args.no_bpf_filters),
    ]
    cmd += [flag for flag, enabled in bool_flags if enabled]

    async with _profiler_lock:
        if profiler_process and profiler_process.returncode is None:
            return False

        if profiler_process:
            await profiler_process.wait()
            profiler_process = None

        try:
            profiler_process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )
            return True
        except Exception as error:
            log.error("Error starting profiler: %s", error)
            return False


async def stop_profiler():
    global profiler_process

    async with _profiler_lock:
        if not profiler_process:
            return False

        process = profiler_process
        if process.returncode is not None:
            await process.wait()
            profiler_process = None
            return False

        await terminate_process_async(process)
        profiler_process = None
        return True
