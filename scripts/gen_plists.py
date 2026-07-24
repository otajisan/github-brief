#!/usr/bin/env python3
"""Generate macOS launchd plists for github-brief from config values.

Reads settings from the environment (exported by install.sh after sourcing
config.local.sh) and writes one plist per scheduled job into the target dir.

Add a new scheduled command by appending to JOBS below.
"""
import os
import plistlib
import sys

target_dir = sys.argv[1]
gb_bin = os.environ["GB_BIN"]
path_env = os.environ["GB_PATH_ENV"]
out = os.environ["GB_OUT"]


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


def build(label, args, cal):
    return {
        "Label": label,
        "ProgramArguments": ["/bin/bash", gb_bin, *args],
        "StartCalendarInterval": cal,
        "EnvironmentVariables": {"PATH": path_env},
        "StandardOutPath": f"{out}/logs/{label}.out.log",
        "StandardErrorPath": f"{out}/logs/{label}.err.log",
        "RunAtLoad": False,
    }


for label, (args, cal) in JOBS.items():
    path = os.path.join(target_dir, f"{label}.plist")
    with open(path, "wb") as f:
        plistlib.dump(build(label, args, cal), f)
    print(f"wrote {path}")
