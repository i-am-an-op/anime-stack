#!/usr/bin/env python3
"""Encrypt a consistent state snapshot; restore only into a new held deployment."""

import argparse
import os
import shutil
import subprocess
import sys
import tarfile
from datetime import datetime, timezone
from pathlib import Path

from common import (
    ROOT,
    compose,
    data_dir,
    dotenv,
    operation_lock,
    policy,
    running_services,
    write_private,
)

SOURCE_MEMBERS = [
    "compose.yaml",
    ".env",
    ".env.example",
    ".gitignore",
    "policy.example.json",
    "versions.json",
    "scripts",
    "cloudflare",
    "docs",
    "README.md",
    "LICENSE",
]
RUNTIME_MEMBERS = [
    "policy.json",
    "state",
    "secrets",
    "cloudflare",
    "backup-recipient.txt",
    "ops/hold.json",
    "ops/bootstrap-complete.json",
]


def archive_filter(member):
    if "__pycache__" in Path(member.name).parts or member.name.endswith("/.ab_owner"):
        return None
    if not (member.isfile() or member.isdir()):
        raise ValueError(
            "State snapshot contains a link or special file; inspect it before backing up"
        )
    return member


def create():
    binary = shutil.which("age")
    recipient_file = data_dir() / "backup-recipient.txt"
    if not binary or not recipient_file.is_file():
        raise RuntimeError(
            "Install age and place its public recipient in DATA_DIR/backup-recipient.txt"
        )
    if not (data_dir() / "ops/bootstrap-complete.json").is_file():
        raise RuntimeError("Complete private bootstrap before creating a state backup")
    recipient = recipient_file.read_text().strip()
    if not recipient.startswith("age1") or any(c.isspace() for c in recipient):
        raise ValueError("Expected one age public recipient")
    os.umask(0o077)
    backup_dir = data_dir() / "backups"
    backup_dir.mkdir(mode=0o700, exist_ok=True)
    name = datetime.now(timezone.utc).strftime("state-%Y%m%dT%H%M%S-%fZ.tar.gz.age")
    output = backup_dir / name
    partial = output.with_suffix(output.suffix + ".partial")
    running = running_services()
    try:
        if running:
            compose("stop", "--timeout", "300", *running, timeout=650)
        if running_services():
            raise RuntimeError("Applications must be stopped for a consistent backup")
        with subprocess.Popen(
            [binary, "-r", recipient, "-o", str(partial)],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        ) as encrypted:
            try:
                with tarfile.open(fileobj=encrypted.stdin, mode="w|gz") as archive:
                    for name in SOURCE_MEMBERS:
                        archive.add(ROOT / name, arcname=name, filter=archive_filter)
                    for name in RUNTIME_MEMBERS:
                        source = data_dir() / name
                        if source.exists():
                            archive.add(source, arcname="runtime/" + name, filter=archive_filter)
                encrypted.stdin.close()
                encrypted.wait(timeout=300)
                if encrypted.returncode:
                    raise RuntimeError("age encryption failed")
            except BaseException:
                encrypted.kill()
                encrypted.wait()
                raise
        partial.replace(output)
    finally:
        partial.unlink(missing_ok=True)
        if running and not (data_dir() / "ops/hold.json").exists():
            compose("up", "-d", "--wait", "--wait-timeout", "180", *running, timeout=240)
    keep = int(policy()["backup_keep"])
    for old in sorted(backup_dir.glob("state-*.tar.gz.age"), reverse=True)[keep:]:
        if old.is_file() and not old.is_symlink():
            old.unlink()
    print("Encrypted state backup created: " + str(output))


def restore(archive_path, target):
    """Validate every archive member before extracting a decrypted snapshot."""
    target = Path(target).resolve()
    if target.exists():
        raise ValueError("Restore target must not already exist")
    with tarfile.open(archive_path, "r:gz") as archive:
        members = archive.getmembers()
        allowed = set(SOURCE_MEMBERS) | {"runtime"}
        names = {m.name for m in members}
        required = {
            "compose.yaml",
            ".env",
            "runtime/policy.json",
            "runtime/secrets/credentials.json",
        }
        if not required.issubset(names):
            raise ValueError("Not an anime-stack state backup")
        for member in members:
            p = Path(member.name)
            if p.is_absolute() or ".." in p.parts or not p.parts or p.parts[0] not in allowed:
                raise ValueError("Unsafe or unexpected archive path")
            if (
                p.parts[0] == "runtime"
                and len(p.parts) > 1
                and p.parts[1] not in {Path(n).parts[0] for n in RUNTIME_MEMBERS}
            ):
                raise ValueError("Unexpected runtime data in archive")
            if not (member.isfile() or member.isdir()):
                raise ValueError("Archive contains links or special files")
        target.mkdir(mode=0o700, parents=True)
        archive.extractall(target, filter="data")
    original = (target / ".env").read_text()
    config = dotenv(target / ".env")
    config.update(
        DATA_DIR="./runtime",
        MEDIA_DIR="./runtime/media",
        COMPOSE_PROJECT_NAME="anime-stack-recovery",
    )
    write_private(target / "runtime/recovery/original.env", original)
    write_private(target / ".env", "\n".join(f"{k}={v}" for k, v in config.items()) + "\n")
    hold = target / "runtime/ops/hold.json"
    if not hold.exists():
        write_private(
            hold,
            {
                "reason": "restored_backup_review_required",
                "at": datetime.now(timezone.utc).isoformat(),
            },
        )
    print(
        "Restored into a new held deployment. Review paths, media, ports and network before explicit resume."
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("create")
    restored = sub.add_parser("restore")
    restored.add_argument("archive")
    restored.add_argument("--to", required=True, dest="target")
    args = parser.parse_args()
    try:
        if args.command == "create":
            with operation_lock():
                create()
        else:
            restore(args.archive, args.target)
    except Exception as exc:
        print(f"Backup failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
