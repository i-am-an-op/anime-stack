#!/usr/bin/env python3
"""Initialize once, then privately bootstrap and verify both application logins."""

import argparse
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import time
import urllib.error

from common import (
    API,
    GIB,
    ROOT,
    data_dir,
    media_dir,
    operation_lock,
    policy,
    read_json,
    settings,
    versions,
    write_private,
)


def initialize():
    os.umask(0o077)
    if not (ROOT / ".env").exists():
        value = (
            (ROOT / ".env.example")
            .read_text()
            .replace("PUID=1000", f"PUID={os.getuid()}")
            .replace("PGID=1000", f"PGID={os.getgid()}")
        )
        write_private(ROOT / ".env", value)
    from preflight import validate_settings

    config = settings()
    validate_settings(config)
    if (
        data_dir() == ROOT
        or data_dir() in ROOT.parents
        or media_dir() == ROOT
        or media_dir() in ROOT.parents
    ):
        raise ValueError("Runtime directories must be distinct from source and its parents")
    for name in [
        "state/qbittorrent/qBittorrent",
        "state/autobangumi/config",
        "state/autobangumi/data",
        "secrets",
        "ops",
        "backups",
    ]:
        (data_dir() / name).mkdir(parents=True, exist_ok=True, mode=0o700)
    (media_dir() / "Bangumi").mkdir(parents=True, exist_ok=True, mode=0o700)
    if not (data_dir() / "policy.json").exists():
        value = read_json(ROOT / "policy.example.json")
        free = shutil.disk_usage(media_dir()).free / GIB
        if free < 3:
            raise RuntimeError("At least 3 GiB free is required for initial policy sizing")
        value["stop_free_gib"] = round(min(25, max(1, free * 0.10)), 2)
        value["warning_free_gib"] = round(
            min(40, max(value["stop_free_gib"] + 0.5, free * 0.20)), 2
        )
        value["media_budget_gib"] = max(1, int(free - value["warning_free_gib"]))
        write_private(data_dir() / "policy.json", value)
    credential_path = data_dir() / "secrets/credentials.json"
    if not credential_path.exists():
        if (
            any((data_dir() / "state").rglob("*.db"))
            or (data_dir() / "state/qbittorrent/qBittorrent/qBittorrent.conf").exists()
        ):
            raise RuntimeError(
                "Existing application state found without credentials; refusing to reset it"
            )
        write_private(
            credential_path,
            {
                s: {"username": "admin", "password": secrets.token_urlsafe(32)}
                for s in ["qbittorrent", "autobangumi"]
            },
        )
    credentials = read_json(credential_path)
    qb = data_dir() / "state/qbittorrent/qBittorrent/qBittorrent.conf"
    if not qb.exists():
        salt = secrets.token_bytes(16)
        digest = hashlib.pbkdf2_hmac(
            "sha512", credentials["qbittorrent"]["password"].encode(), salt, 100000
        )
        hashed = base64.b64encode(salt).decode() + ":" + base64.b64encode(digest).decode()
        write_private(
            qb,
            "[LegalNotice]\nAccepted=true\n\n[Preferences]\n"
            "WebUI\\Username=admin\n"
            f'WebUI\\Password_PBKDF2="@ByteArray({hashed})"\n'
            "WebUI\\LocalHostAuth=true\nWebUI\\AuthSubnetWhitelistEnabled=false\n"
            "WebUI\\CSRFProtection=true\nWebUI\\HostHeaderValidation=true\n"
            f'WebUI\\ServerDomains="qbittorrent;localhost;127.0.0.1;{config["QB_ADDRESS"]}"\n'
            f"WebUI\\Port={config['QB_WEB_PORT']}\n\n[BitTorrent]\nSession\\Port={config['PEER_PORT']}\n",
        )
    ab = data_dir() / "state/autobangumi/config/config.json"
    if not ab.exists():
        write_private(
            ab,
            {
                "program": {"rss_time": 900, "rename_time": 60, "webui_port": 7892},
                "downloader": {
                    "type": "qbittorrent",
                    "host": "qbittorrent:" + config["QB_WEB_PORT"],
                    **credentials["qbittorrent"],
                    "path": "/downloads/Bangumi",
                    "ssl": False,
                },
                "rss_parser": {
                    "enable": True,
                    "filter": ["720", "\\d+-\\d+"],
                    "language": "zh",
                    "engine": "classic",
                },
                "bangumi_manage": {
                    "enable": True,
                    "eps_complete": False,
                    "rename_method": "pn",
                    "group_tag": False,
                    "remove_bad_torrent": False,
                    "revision_conflict_policy": "hold",
                },
                "security": {
                    "login_whitelist": [],
                    "login_tokens": [],
                    "mcp_whitelist": [],
                    "mcp_tokens": [],
                },
                "llm": {"enable": False},
                "notification": {"enable": False},
                "update": {"channel": "stable", "auto_check": False},
            },
        )
    print(
        "Initialized private runtime and detected the current UID/GID. Review .env and runtime policy before startup."
    )


def expected_preferences():
    limits = policy()
    config = settings()
    public = config.get("QB_PUBLIC_HOST", "")
    if public and not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]*[a-z0-9])?", public):
        raise ValueError("QB_PUBLIC_HOST must be a plain lowercase DNS hostname")
    hosts = ["qbittorrent", "localhost", "127.0.0.1", config["QB_ADDRESS"]] + (
        [public] if public else []
    )
    return {
        "save_path": "/downloads/Bangumi",
        "temp_path_enabled": False,
        "incomplete_files_ext": True,
        "preallocate_all": False,
        "upnp": False,
        "web_ui_upnp": False,
        "dl_limit": limits["max_download_bytes_per_second"],
        "alt_dl_limit": limits["max_download_bytes_per_second"],
        "up_limit": limits["max_upload_bytes_per_second"],
        "alt_up_limit": limits["max_upload_bytes_per_second"],
        "queueing_enabled": True,
        "dont_count_slow_torrents": False,
        "max_active_downloads": limits["max_active_downloads"],
        "max_active_uploads": limits["max_active_uploads"],
        "max_active_torrents": limits["max_active_downloads"] + limits["max_active_uploads"],
        "max_active_checking_torrents": 1,
        "web_ui_domain_list": ";".join(hosts),
        "bypass_local_auth": False,
        "bypass_auth_subnet_whitelist_enabled": False,
        "web_ui_csrf_protection_enabled": True,
        "web_ui_host_header_validation_enabled": True,
        "web_ui_clickjacking_protection_enabled": True,
        "web_ui_reverse_proxy_enabled": True,
        "web_ui_reverse_proxies_list": config["PROXY_ADDRESS"],
        "web_ui_session_timeout": 3600,
    }


def bootstrap():
    qb = API("qbittorrent").login()
    expected = expected_preferences()
    qb.preferences(expected)
    # Changes are applied on the application event loop.
    for _ in range(20):
        actual = qb.preferences()
        mismatch = [k for k, v in expected.items() if actual.get(k) != v]
        if not mismatch:
            break
        time.sleep(0.25)
    if mismatch:
        raise RuntimeError("qBittorrent settings were not applied: " + ", ".join(mismatch))
    version = qb.request("/api/v2/app/version", raw=True)
    if version != "v" + versions()["qbittorrent"]:
        raise RuntimeError("Unexpected qBittorrent version")
    credentials = read_json(data_dir() / "secrets/credentials.json")["autobangumi"]
    ab = API("autobangumi", credentials)
    try:
        ab.login()
    except urllib.error.HTTPError as exc:
        if exc.code != 401 or (data_dir() / "ops/bootstrap-complete.json").exists():
            raise
        ab = API("autobangumi", {"username": "admin", "password": "adminadmin"}).login()
        ab.request("/api/v1/auth/update", method="POST", data=credentials)
        ab.logout()
        ab = API("autobangumi", credentials).login()
    health = ab.request("/health")
    if health.get("version") != versions()["autobangumi"] or not health.get("db_ok"):
        raise RuntimeError("AutoBangumi version/database check failed")
    config = ab.request("/api/v1/config/get")
    desired_host = "qbittorrent:" + settings()["QB_WEB_PORT"]
    if config["downloader"]["host"] != desired_host:
        # The API replaces the full model; preserve all other settings and masked secrets.
        config["downloader"]["host"] = desired_host
        ab.request("/api/v1/config/update", method="PATCH", data=config)
    if ab.request("/api/v1/check/downloader") is not True:
        raise RuntimeError("AutoBangumi cannot authenticate to qBittorrent")
    config = ab.request("/api/v1/config/get")
    if config["bangumi_manage"]["eps_complete"] or config["bangumi_manage"]["remove_bad_torrent"]:
        raise RuntimeError("Unsafe initial AutoBangumi backfill/deletion settings")
    if config["security"]["mcp_whitelist"] or config["security"]["login_tokens"]:
        raise RuntimeError("Unexpected AutoBangumi authentication bypass")
    result = {
        "qbittorrent": version,
        "autobangumi": health["version"],
        "downloader_connection": True,
        "settings_verified": len(expected),
        "torrent_count": len(qb.torrents()),
    }
    write_private(data_dir() / "ops/bootstrap-complete.json", result)
    qb.logout()
    ab.logout()
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=["init", "bootstrap"])
    args = parser.parse_args()
    with operation_lock():
        if args.command == "init":
            initialize()
        else:
            bootstrap()
