#!/usr/bin/env python3
"""Initialize, validate and deploy the private anime stack."""

import argparse
import json
import os
import sys

import initialize
import preflight
from common import ROOT, compose, data_dir, operation_lock, settings


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "command", choices=("init", "check", "up", "verify", "status", "stop", "cloudflare")
    )
    args = parser.parse_args()
    if args.command == "init":
        with operation_lock():
            initialize.initialize()
        return
    if not (ROOT / ".env").is_file():
        raise RuntimeError("Run `python3 scripts/manage.py init` first")
    if args.command == "check":
        preflight.check()
    elif args.command == "status":
        print(compose("ps").stdout.strip())
    elif args.command == "verify":
        import verify

        with operation_lock():
            verify.verify()
    elif args.command == "stop":
        with operation_lock():
            compose("stop", "--timeout", "300", timeout=650)
        print("Containers stopped; files and credentials retained.")
    elif args.command == "cloudflare":
        preflight.check()
        token = data_dir() / "secrets/cloudflared-token"
        if (
            not (data_dir() / "ops/bootstrap-complete.json").is_file()
            or not token.is_file()
            or token.stat().st_mode & 0o077
            or token.stat().st_uid != os.getuid()
            or not token.read_text().strip()
        ):
            raise RuntimeError(
                "Complete private bootstrap and install an owner-readable 0600 connector token first"
            )
        if not all(settings().get(k) for k in ("QB_PUBLIC_HOST", "AB_PUBLIC_HOST")):
            raise RuntimeError(
                "Configure public hostnames and Access protection first; see docs/cloudflare.md"
            )
        # Reapply the explicit allowed-host list if the public names were added later.
        with operation_lock():
            if (data_dir() / "ops/hold.json").exists():
                raise RuntimeError("Resolve the disk-guard hold before configuring public access")
            initialize.bootstrap()
            compose(
                "--profile",
                "cloudflare",
                "up",
                "-d",
                "--no-deps",
                "--wait",
                "--wait-timeout",
                "120",
                "cloudflared",
                timeout=180,
            )
        print("Connector started. Verify Access/MFA and both browser logins.")
    else:
        preflight.check()
        with operation_lock():
            if (data_dir() / "ops/hold.json").exists():
                raise RuntimeError(
                    "A disk-guard hold is active; use guard.py resume after recovering space"
                )
            try:
                compose(
                    "up",
                    "-d",
                    "--wait",
                    "--wait-timeout",
                    "180",
                    "qbittorrent",
                    "autobangumi",
                    timeout=900,
                )
                initialize.bootstrap()
                import guard

                result = guard.check()
                if result["level"] in ("stop", "held"):
                    raise RuntimeError("Disk guard stopped startup; inspect its status and policy")
            except Exception:
                compose(
                    "stop",
                    "--timeout",
                    "60",
                    "autobangumi",
                    "qbittorrent",
                    check=False,
                    timeout=150,
                )
                raise
        config = settings()
        print(
            json.dumps(
                {
                    "status": "ready",
                    "qbittorrent": "http://127.0.0.1:" + config["QB_WEB_PORT"],
                    "autobangumi": "http://127.0.0.1:" + config["AB_WEB_PORT"],
                    "credentials_file": str(data_dir() / "secrets/credentials.json"),
                },
                indent=2,
            )
        )


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"Operation failed: {type(exc).__name__}: {exc}", file=sys.stderr)
        sys.exit(1)
