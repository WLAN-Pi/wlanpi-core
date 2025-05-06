import subprocess
import wlanpi_core.profiler.models as models
from wlanpi_core.utils.general import run_command


def start_profiler(args: models.Start):
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

    result = run_command(cmd)

    return result


def stop_profiler():
    cmd = "/bin/systemctl stop wlanpi-profiler"

    result = run_command(cmd)

    return result
