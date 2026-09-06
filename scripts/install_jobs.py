#!/usr/bin/env python3
"""Install the owner's cron entries, preserving all unrelated entries."""

import argparse
import os
import shlex
import shutil
import sys

from common import ROOT, data_dir, run, settings

BEGIN = "# BEGIN anime-stack managed jobs"
END = "# END anime-stack managed jobs"


def updated_crontab(
    old,
    root,
    *,
    with_backup=True,
    python="/usr/bin/python3",
    logger="/usr/bin/logger",
    project="anime-stack",
):
    begin, end = f"# BEGIN {project} managed jobs", f"# END {project} managed jobs"
    if "\n" in root or "%" in root:
        raise ValueError("Unsupported cron path")
    if old.count(begin) != old.count(end) or old.count(begin) > 1:
        raise ValueError("Malformed managed cron block; refusing to replace it")
    if begin in old:
        start, stop = old.index(begin), old.index(end) + len(end)
        if stop < start:
            raise ValueError("Malformed cron block")
        old = old[:start] + old[stop:]
    script = shlex.quote(root + "/scripts/guard.py")
    backup = shlex.quote(root + "/scripts/backup.py")
    block = (
        f"{begin}\n"
        f"* * * * * /usr/bin/env PATH=/usr/local/bin:/usr/bin:/bin {shlex.quote(python)} {script} check --quiet 2>&1 | {shlex.quote(logger)} -t {shlex.quote(project + '-guard')}\n"
        + (
            f"17 4 * * * /usr/bin/env PATH=/usr/local/bin:/usr/bin:/bin {shlex.quote(python)} {backup} create 2>&1 | {shlex.quote(logger)} -t {shlex.quote(project + '-backup')}\n"
            if with_backup
            else ""
        )
        + f"{end}\n"
    )
    return old.rstrip() + ("\n\n" if old.strip() else "") + block


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--with-backup", action="store_true")
    args = parser.parse_args()
    if not shutil.which("crontab") or not shutil.which("logger"):
        raise RuntimeError("Install and enable a cron daemon and logger first")
    if args.with_backup and (
        not shutil.which("age") or not (data_dir() / "backup-recipient.txt").is_file()
    ):
        raise RuntimeError(
            "Install age and configure its public recipient before scheduling backups"
        )
    if not os.access(sys.executable, os.X_OK):
        raise RuntimeError("Python executable is not usable by cron")
    current = run(["crontab", "-l"], check=False)
    if current.returncode not in (0, 1) or (current.returncode == 1 and current.stdout):
        raise RuntimeError("Unable to inspect current crontab")
    run(
        ["crontab", "-"],
        input=updated_crontab(
            current.stdout,
            str(ROOT),
            with_backup=args.with_backup,
            python=sys.executable,
            logger=shutil.which("logger"),
            project=settings()["COMPOSE_PROJECT_NAME"],
        ),
    )
    print(
        "Installed one-minute guard"
        + (" and daily 04:17 server-time encrypted backup." if args.with_backup else ".")
    )
