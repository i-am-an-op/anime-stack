"""Validate local Linux deployment requirements without installing system packages."""

import ipaddress
import json
import os
import platform
import re
import shutil
import socket
import sys
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from common import ROOT, compose, data_dir, dotenv, media_dir, run, settings


def validate_settings(config):
    if not re.fullmatch(r"[a-z0-9][a-z0-9_-]{0,47}", config["COMPOSE_PROJECT_NAME"]):
        raise ValueError("Use a lowercase Compose project name (1-48 characters)")
    for key in ("PUID", "PGID"):
        if not config[key].isdigit() or not 0 < int(config[key]) < 2**31:
            raise ValueError(key + " must be a non-root numeric ID")
    ports = [int(config[k]) for k in ("QB_WEB_PORT", "AB_WEB_PORT", "PEER_PORT")]
    if len(set(ports)) != 3 or any(p < 1024 or p > 65535 for p in ports):
        raise ValueError("Use three distinct ports between 1024 and 65535")
    subnet = ipaddress.IPv4Network(config["NETWORK_SUBNET"], strict=True)
    private_ranges = [
        ipaddress.IPv4Network(x) for x in ("10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16")
    ]
    if not any(subnet.subnet_of(n) for n in private_ranges) or not 16 <= subnet.prefixlen <= 28:
        raise ValueError("Use an RFC1918 IPv4 subnet with prefix /16 through /28")
    addresses = [
        ipaddress.IPv4Address(config[k]) for k in ("QB_ADDRESS", "AB_ADDRESS", "PROXY_ADDRESS")
    ]
    reserved = {subnet.network_address, subnet.broadcast_address, subnet.network_address + 1}
    if len(set(addresses)) != 3 or any(a not in subnet or a in reserved for a in addresses):
        raise ValueError("Service IPs must be unique usable addresses, excluding the gateway")
    for key in ("QB_PUBLIC_HOST", "AB_PUBLIC_HOST"):
        host = config.get(key, "")
        if host and (
            len(host) > 253
            or not all(
                re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", x) for x in host.split(".")
            )
        ):
            raise ValueError(key + " must be a lowercase DNS hostname without a port")
    for key in ("DATA_DIR", "MEDIA_DIR"):
        if not config[key] or any(c in config[key] for c in ":%~\r\n"):
            raise ValueError(
                key + " must be a literal path without colons, percent signs or tildes"
            )
    try:
        ZoneInfo(config["TZ"])
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("TZ must be an installed IANA timezone") from exc
    return subnet


def validate_policy(value):
    for key in ("stop_free_gib", "warning_free_gib", "media_budget_gib"):
        if not isinstance(value[key], (int, float)) or not 0 < value[key] < 10**9:
            raise ValueError("Invalid disk policy value: " + key)
    if value["warning_free_gib"] <= value["stop_free_gib"]:
        raise ValueError("Warning threshold must be above the stop threshold")
    for key in (
        "max_download_bytes_per_second",
        "max_upload_bytes_per_second",
        "max_active_downloads",
        "max_active_uploads",
        "backup_keep",
    ):
        if type(value[key]) is not int or value[key] <= 0:
            raise ValueError("Expected a positive integer: " + key)
    return value


def check():
    if platform.system() != "Linux" or sys.version_info < (3, 12):
        raise RuntimeError("Host automation requires Linux and Python 3.12 or newer")
    if platform.machine() not in ("x86_64", "aarch64", "arm64"):
        raise RuntimeError("The pinned images require Linux amd64 or arm64")
    config = settings()
    unknown = set(dotenv(ROOT / ".env")) - set(dotenv(ROOT / ".env.example"))
    if unknown:
        raise ValueError(
            "Unknown .env keys; store management tokens separately: " + ", ".join(sorted(unknown))
        )
    subnet = validate_settings(config)
    if int(config["PUID"]) != os.getuid() or int(config["PGID"]) != os.getgid():
        raise RuntimeError("Run as the non-root user whose PUID/PGID appear in .env")
    for executable in ("docker", "tar", "du"):
        if not shutil.which(executable):
            raise RuntimeError("Missing prerequisite: " + executable)
    context = json.loads(run(["docker", "context", "inspect"]).stdout)[0]
    endpoint = os.environ.get("DOCKER_HOST", context["Endpoints"]["docker"]["Host"])
    if not endpoint.startswith("unix://"):
        raise RuntimeError(
            "Run the scripts on the Docker server; remote Docker contexts are unsupported"
        )
    server = json.loads(run(["docker", "info", "--format", "{{json .}}"]).stdout)
    if int(server["ServerVersion"].split(".")[0]) < 28:
        raise RuntimeError("Docker Engine 28+ is required for loopback port isolation")
    if any("rootless" in s or "userns" in s for s in server.get("SecurityOptions", [])):
        raise RuntimeError(
            "Rootless Docker and user namespace remapping need separate ownership validation"
        )
    version = run(["docker", "compose", "version", "--short"]).stdout.strip().lstrip("v")
    numbers = tuple(int(x) for x in version.split(".")[:2])
    if numbers < (2, 24):
        raise RuntimeError("Docker Compose 2.24+ is required")
    for path in (data_dir(), media_dir()):
        if path == ROOT or path == Path("/") or path in ROOT.parents:
            raise RuntimeError("Runtime paths must not be the source directory or its parent")
        if not path.is_dir() or not os.access(path, os.R_OK | os.W_OK | os.X_OK):
            raise RuntimeError("Initialize writable runtime and media directories first")
    if media_dir() == data_dir() or media_dir() in data_dir().parents:
        raise RuntimeError("MEDIA_DIR must not contain DATA_DIR")
    validate_policy(json.loads((data_dir() / "policy.json").read_text()))
    if shutil.disk_usage(media_dir()).free <= 2 * 1024**3:
        raise RuntimeError("At least 2 GiB of free media space is required before startup")
    ids = run(["docker", "network", "ls", "--quiet"]).stdout.split()
    networks = json.loads(run(["docker", "network", "inspect", *ids]).stdout) if ids else []
    for network in networks:
        if (network.get("Labels") or {}).get("com.docker.compose.project") == config[
            "COMPOSE_PROJECT_NAME"
        ]:
            continue
        for ipam in network.get("IPAM", {}).get("Config", []) or []:
            other = ipaddress.ip_network(ipam.get("Subnet", "0.0.0.0/32"), strict=False)
            if other.version == 4 and subnet.overlaps(other):
                raise RuntimeError("NETWORK_SUBNET overlaps an existing Docker network")
    # Existing project containers own their ports. Fresh projects must reserve free ports.
    existing = compose("ps", "--all", "--quiet").stdout.strip()
    if not existing:
        for key in ("QB_WEB_PORT", "AB_WEB_PORT", "PEER_PORT"):
            kinds = (
                (socket.SOCK_STREAM, socket.SOCK_DGRAM)
                if key == "PEER_PORT"
                else (socket.SOCK_STREAM,)
            )
            for kind in kinds:
                with socket.socket(socket.AF_INET, kind) as sock:
                    sock.bind(("0.0.0.0" if key == "PEER_PORT" else "127.0.0.1", int(config[key])))
    compose("config", "--quiet")
    print("Preflight passed: local Linux Docker, ownership, configuration, network and ports.")
