#!/usr/bin/env python3
"""Generate macOS launchd plists for github-brief from config values.

Reads settings from the environment (exported by install.sh after sourcing
config.local.sh) and writes one plist per job into the target dir, printing
the label of every plist it wrote (install.sh loads exactly those).

Add a new scheduled command by appending to JOBS below.
"""
import os
import plistlib
import sys

target_dir = sys.argv[1]
gb_bin = os.environ["GB_BIN"]
path_env = os.environ["GB_PATH_ENV"]
out = os.environ["GB_OUT"]
serve_sh = os.environ["GB_SERVE"]


def _int(name, default):
    return int(os.environ.get(name, default))


daily_cal = [
    {"Weekday": int(d), "Hour": _int("DAILY_HOUR", "9"), "Minute": _int("DAILY_MINUTE", "0")}
    for d in os.environ.get("DAILY_WEEKDAYS", "1 2 3 4 5").split()
]
weekly_cal = {
    "Weekday": _int("WEEKLY_WEEKDAY", "5"),
    "Hour": _int("WEEKLY_HOUR", "10"),
    "Minute": _int("WEEKLY_MINUTE", "30"),
}

# label -> (args, StartCalendarInterval)
JOBS = {
    "com.github-brief.daily": (["pr-brief", "daily"], daily_cal),
    "com.github-brief.weekly": (["pr-brief", "weekly"], weekly_cal),
}


# The one deliberate exception to the heartbeat rule: the history-hub server.
# Started at login and restarted if it dies, so http://localhost:PORT/ survives
# a reboot. Opt-in via SERVE_AT_LOGIN=1; it only serves OUTPUT_DIR on loopback.
SERVE_LABEL = "com.github-brief.serve"


def _base(label, program):
    return {
        "Label": label,
        "ProgramArguments": program,
        "EnvironmentVariables": {"PATH": path_env},
        "StandardOutPath": f"{out}/logs/{label}.out.log",
        "StandardErrorPath": f"{out}/logs/{label}.err.log",
    }


def build(label, args, cal):
    return {
        **_base(label, ["/bin/bash", gb_bin, *args]),
        "StartCalendarInterval": cal,
        "RunAtLoad": False,
    }


def build_serve():
    return {
        **_base(SERVE_LABEL, ["/bin/bash", serve_sh]),
        "RunAtLoad": True,
        "KeepAlive": True,
    }


plists = {label: build(label, args, cal) for label, (args, cal) in JOBS.items()}
if os.environ.get("SERVE_AT_LOGIN", "0") == "1":
    plists[SERVE_LABEL] = build_serve()

for label, plist in plists.items():
    with open(os.path.join(target_dir, f"{label}.plist"), "wb") as f:
        plistlib.dump(plist, f)
    print(label)
