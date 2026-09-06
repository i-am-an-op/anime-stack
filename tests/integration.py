"""Destructive lifecycle checks for a disposable, empty test deployment only."""

import json
import os
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import backup
import guard
from common import API, data_dir, operation_lock, running_services, settings, write_private


def main():
    if os.environ.get("ANIME_STACK_TESTING") != "1" or "test" not in settings()[
        "COMPOSE_PROJECT_NAME"
    ].split("-"):
        raise RuntimeError(
            "Requires ANIME_STACK_TESTING=1 and a disposable project name containing 'test'"
        )
    qb = API("qbittorrent").login()
    try:
        if qb.torrents():
            raise RuntimeError("Refusing lifecycle tests with existing torrents")
    finally:
        qb.logout()
    recipient_file = data_dir() / "backup-recipient.txt"
    if recipient_file.exists():
        raise RuntimeError("Refusing to overwrite an existing backup recipient")
    before = set((data_dir() / "backups").glob("*.age"))
    with tempfile.TemporaryDirectory(prefix="anime-stack-recovery-test-") as td:
        temp = Path(td)
        identity = temp / "identity.txt"
        subprocess.run(["age-keygen", "-o", str(identity)], check=True, capture_output=True)
        recipient = subprocess.run(
            ["age-keygen", "-y", str(identity)], check=True, capture_output=True, text=True
        ).stdout.strip()
        write_private(recipient_file, recipient + "\n")
        try:
            with operation_lock():
                backup.create()
                assert set(running_services()) == {"qbittorrent", "autobangumi"}
                guard.trip("integration_test_hold")
                assert not running_services() and guard.check()["level"] == "held"
                backup.create()
                assert not running_services(), "Backup must preserve the hold"
                newest = max((data_dir() / "backups").glob("*.age"), key=lambda p: p.name)
                plain = temp / "state.tar.gz"
                subprocess.run(
                    ["age", "-d", "-i", str(identity), "-o", str(plain), str(newest)],
                    check=True,
                    capture_output=True,
                )
                restored = temp / "restored"
                backup.restore(plain, restored)
                assert (
                    json.loads((restored / "runtime/ops/hold.json").read_text())["reason"]
                    == "integration_test_hold"
                )
                assert (restored / "runtime/secrets/credentials.json").read_bytes() == (
                    data_dir() / "secrets/credentials.json"
                ).read_bytes()
                assert not (restored / "runtime/media").exists()
                db_path = restored / "runtime/state/autobangumi/data/data.db"
                with sqlite3.connect(str(db_path)) as db:
                    assert db.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
                    assert db.execute("SELECT COUNT(*) FROM rssitem").fetchone()[0] == 0
                guard.resume()
                assert not guard.LATCH.exists() and set(running_services()) == {
                    "qbittorrent",
                    "autobangumi",
                }
            print(
                "Lifecycle checks passed: running backup, latched stop, held backup, full SQLite/WAL recovery and explicit resume."
            )
        finally:
            recipient_file.unlink(missing_ok=True)
            for path in set((data_dir() / "backups").glob("*.age")) - before:
                path.unlink()


if __name__ == "__main__":
    main()
