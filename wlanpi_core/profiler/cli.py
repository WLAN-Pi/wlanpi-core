import asyncio

import wlanpi_core.profiler.models as models


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

    try:
        # keep refrence of process id
        profiler_process = await asyncio.create_subprocess_exec(
            *cmd, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
        )
        return True
    except Exception as e:
        print(f"Error starting profiler: {e}")
        return False


def stop_profiler():
    global profiler_process

    if profiler_process and profiler_process.returncode is None:
        profiler_process.terminate()
        return True
    else:
        return False
