#!/usr/bin/env python3
"""Check tracked source files for runtime data, broken links and mutable pins."""

import json
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def check():
    tracked = (
        subprocess.run(["git", "ls-files", "-z"], cwd=ROOT, check=True, capture_output=True)
        .stdout.decode()
        .split("\0")
    )
    tracked = [p for p in tracked if p]
    if not tracked:
        raise RuntimeError("No tracked files; stage the intended publication source first")
    forbidden_parts = {
        "runtime",
        "state",
        "secrets",
        "media",
        "ops",
        "backups",
        ".local",
        ".venv",
        "__pycache__",
    }
    secret_patterns = [
        r"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----",
        r"AGE-SECRET-KEY-1[0-9A-Z]{30,}",
        r"gh[pousr]_[A-Za-z0-9]{30,}",
        r"github_pat_[A-Za-z0-9_]{30,}",
    ]
    errors = []
    for name in tracked:
        path = Path(name)
        if (
            set(path.parts) & forbidden_parts
            or (path.name.startswith(".env") and path.name != ".env.example")
            or path.name in {"backup-identity.txt", "credentials.json", "cloudflared-token"}
            or path.suffix in {".age", ".pem", ".key", ".db", ".sqlite"}
            or (path.name.startswith("state") and path.name.endswith(".tar.gz"))
        ):
            errors.append("Runtime or secret path tracked: " + name)
        source = ROOT / path
        if source.is_symlink():
            errors.append("Unexpected source symlink: " + name)
            continue
        content = source.read_text()
        if any(re.search(pattern, content) for pattern in secret_patterns):
            errors.append("Potential credential in: " + name)
        if path.suffix == ".json":
            json.loads(content)
        if path.suffix == ".md":
            for target in re.findall(r"\]\(([^\s)]+)\)", content):
                if "://" in target or target.startswith("#"):
                    continue
                target = target.split("#", 1)[0]
                if target and not (source.parent / target).exists():
                    errors.append("Broken local link in " + name + ": " + target)
        if name.startswith(".github/workflows/"):
            if "pull_request_target" in content:
                errors.append("Privileged pull_request_target workflow: " + name)
            for action in re.findall(r"uses:\s*([^\s]+)", content):
                if not action.startswith("./") and not re.fullmatch(r"[^@]+@[0-9a-f]{40}", action):
                    errors.append("Action must use a full commit SHA: " + name)
    compose = (ROOT / "compose.yaml").read_text()
    images = re.findall(r"^\s+image:\s+(\S+)", compose, re.MULTILINE)
    if len(images) != 3 or any(
        not re.fullmatch(r".+:[^@]+@sha256:[0-9a-f]{64}", image) or ":latest@" in image
        for image in images
    ):
        errors.append("All three images need version tags and immutable digests")
    versions = json.loads((ROOT / "versions.json").read_text())
    for name, image in zip(("qbittorrent", "autobangumi", "cloudflared"), images):
        if ":" + versions[name] not in image:
            errors.append("Version metadata differs from image pin: " + name)
    if errors:
        raise RuntimeError("\n".join(errors))
    print(f"Repository checks passed for {len(tracked)} tracked text files.")


if __name__ == "__main__":
    check()
