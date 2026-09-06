#!/usr/bin/env python3
"""Stop acquisition on disk pressure; never delete files or automatically resume."""

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone

from common import (
    API,
    GIB,
    compose,
    data_dir,
    media_dir,
    operation_lock,
    read_json,
    run,
    running_services,
    write_private,
)
from common import policy as read_policy

LATCH = data_dir() / "ops/hold.json"
STATUS = data_dir() / "ops/guard-status.json"


def now():
    return datetime.now(timezone.utc).isoformat()


def assess(free, used, remaining, policy):
    """Reserve queued payloads conservatively, including manually stopped tasks."""
    if min(free, used, remaining) < 0:
        return "stop", "invalid_space_measurement"
    floor = policy["stop_free_gib"] * GIB
    if free <= floor:
        return "stop", "free_space_below_stop_threshold"
    if remaining > free - floor:
        return "stop", "queued_payload_exceeds_available_budget"
    if free <= policy["warning_free_gib"] * GIB:
        return "warning", "free_space_below_warning_threshold"
    if used >= policy["media_budget_gib"] * GIB:
        return "warning", "media_above_soft_budget"
    return "ok", "within_budget"


def bounded_preferences(preferences, policy):
    limit = policy["max_download_bytes_per_second"]
    return (
        0 < preferences["dl_limit"] <= limit
        and 0 < preferences["alt_dl_limit"] <= limit
        and preferences["queueing_enabled"]
        and not preferences["dont_count_slow_torrents"]
        and 0 < preferences["max_active_downloads"] <= policy["max_active_downloads"]
    )


def sample():
    policy = read_policy()
    free = shutil.disk_usage(media_dir()).free
    used = int(run(["du", "-s", "-B1", str(media_dir())]).stdout.split()[0])
    # Disk emergency must not depend on a working API.
    level, reason = assess(free, used, 0, policy)
    if level == "stop":
        return {
            "at": now(),
            "level": level,
            "reason": reason,
            "free_gib": free / GIB,
            "used_gib": used / GIB,
            "remaining_gib": None,
        }
    qb = API("qbittorrent").login()
    try:
        torrents = qb.torrents()
        remaining = sum(max(0, int(t["amount_left"])) for t in torrents)
        level, reason = assess(free, used, remaining, policy)
        if not bounded_preferences(qb.preferences(), policy):
            level, reason = "stop", "download_limits_outside_checked_policy"
        return {
            "at": now(),
            "level": level,
            "reason": reason,
            "free_gib": round(free / GIB, 3),
            "used_gib": round(used / GIB, 3),
            "remaining_gib": round(remaining / GIB, 3),
            "torrents": len(torrents),
            "metadata_pending": sum(t["size"] == 0 for t in torrents),
        }
    finally:
        qb.logout()


def stop_services():
    # Persist stopped torrents when the API is usable; container stop is the fallback.
    try:
        qb = API("qbittorrent").login()
        try:
            qb.stop_torrents()
        finally:
            qb.logout()
    except Exception:
        pass
    compose("stop", "--timeout", "60", "autobangumi", "qbittorrent", timeout=150)
    if running_services():
        raise RuntimeError("Could not stop both applications")


def trip(reason):
    # Even an ENOSPC error while writing the latch must still stop the writers.
    try:
        if not LATCH.exists():
            write_private(LATCH, {"at": now(), "reason": reason})
    finally:
        stop_services()


def check():
    if LATCH.exists():
        if running_services():
            stop_services()
        result = {"at": now(), "level": "held", "reason": "explicit_resume_required"}
    elif not running_services():
        result = {"at": now(), "level": "stopped", "reason": "applications_stopped"}
    else:
        try:
            result = sample()
        except Exception as exc:
            result = {
                "at": now(),
                "level": "stop",
                "reason": "monitoring_failed",
                "error_type": type(exc).__name__,
            }
        if result["level"] == "stop":
            trip(result["reason"])
    write_private(STATUS, result)
    return result


def resume():
    if not LATCH.exists():
        raise RuntimeError("There is no disk-guard hold to resume")
    policy = read_policy()
    if shutil.disk_usage(media_dir()).free < policy["warning_free_gib"] * GIB:
        raise RuntimeError("Recover at least the warning free-space threshold before resuming")
    try:
        compose("up", "-d", "--wait", "--wait-timeout", "150", "qbittorrent", timeout=200)
        qb = API("qbittorrent").login()
        try:
            qb.stop_torrents()
        finally:
            qb.logout()
        result = sample()
        if result["level"] == "stop":
            raise RuntimeError(
                "Queued payloads or configured limits still exceed the checked budget"
            )
        compose("up", "-d", "--wait", "--wait-timeout", "150", "autobangumi", timeout=200)
        LATCH.unlink()
        write_private(STATUS, {**result, "resumed_at": now(), "existing_torrents": "stopped"})
        return {
            "status": "resumed",
            "existing_torrents": "remain stopped; resume selected torrents in qBittorrent",
        }
    except Exception:
        stop_services()
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["check", "hold", "resume", "status"])
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()
    try:
        with operation_lock(blocking=args.command != "check") as acquired:
            if not acquired:
                sys.exit(0)
            if args.command == "check":
                result = check()
            elif args.command == "hold":
                trip("operator_hold")
                result = check()
            elif args.command == "resume":
                result = resume()
            else:
                result = {
                    "guard": read_json(STATUS) if STATUS.exists() else None,
                    "held": LATCH.exists(),
                    "running": running_services(),
                }
        if not args.quiet or result.get("level") in ("stop", "warning"):
            print(json.dumps(result, indent=None if args.quiet else 2))
    except Exception as exc:
        print(f"Disk guard failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
