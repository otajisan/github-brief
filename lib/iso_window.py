#!/usr/bin/env python3
"""Compute the deterministic SINCE/UNTIL window for a brief.

Prints "SINCE UNTIL" as ISO8601 with a timezone offset, e.g.
    2026-07-22T14:30:00+09:00 2026-07-29T10:30:00+09:00

  daily   yesterday 00:00 .. today 00:00 (on Monday, back to Friday 00:00)
  weekly  today START_HOUR:MINUTE minus LOOKBACK days .. today WEEKLY_HOUR:MINUTE

usage: iso_window.py MODE TZ_OFFSET_HOURS LOOKBACK_DAYS \
                     WEEKLY_HOUR WEEKLY_MINUTE START_HOUR START_MINUTE

Kept as a file rather than a shell heredoc: bash materializes a here-document
larger than the pipe buffer through a temp file, and that path can block on
macOS — which would hang a scheduled run instead of failing it.
"""
from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone


def iso(moment: datetime) -> str:
    stamp = moment.strftime("%Y-%m-%dT%H:%M:%S%z")
    return stamp[:-2] + ":" + stamp[-2:]


def window(mode: str, now: datetime, lookback: int, weekly_hour: int,
           weekly_minute: int, start_hour: int, start_minute: int):
    if mode == "daily":
        midnight = now.replace(hour=0, minute=0, second=0, microsecond=0)
        back = 3 if now.weekday() == 0 else 1      # Monday covers Fri–Sun
        return midnight - timedelta(days=back), midnight
    until = now.replace(hour=weekly_hour, minute=weekly_minute,
                        second=0, microsecond=0)
    since = (until - timedelta(days=lookback)).replace(
        hour=start_hour, minute=start_minute, second=0, microsecond=0)
    return since, until


def label(since: datetime, until: datetime) -> str:
    """Human-facing window: 2026/07/22 14:30 〜 07/29 10:30 (year once)."""
    right = "%m/%d %H:%M" if since.year == until.year else "%Y/%m/%d %H:%M"
    return f"{since.strftime('%Y/%m/%d %H:%M')} 〜 {until.strftime(right)}"


def main() -> None:
    if sys.argv[1:2] == ["--label"]:
        if len(sys.argv) != 4:
            raise SystemExit(f"usage: {sys.argv[0]} --label SINCE UNTIL")
        since, until = (datetime.fromisoformat(a) for a in sys.argv[2:4])
        print(label(since, until))
        return
    if len(sys.argv) != 8:
        raise SystemExit(f"usage: {sys.argv[0]} MODE TZ LOOKBACK WH WM SH SM")
    mode = sys.argv[1]
    if mode not in ("daily", "weekly"):
        raise SystemExit(f"unknown mode: {mode}")
    tz_hours, lookback, wh, wm, sh, sm = (int(a) for a in sys.argv[2:8])
    now = datetime.now(timezone(timedelta(hours=tz_hours)))
    since, until = window(mode, now, lookback, wh, wm, sh, sm)
    print(iso(since), iso(until))


if __name__ == "__main__":
    main()
