#!/usr/bin/env python3
"""Private acceptance checks. Includes one failed factory-login check per app."""

import json
import stat
import urllib.error
import urllib.request
from datetime import datetime, timezone

from common import API, container, data_dir, settings, versions, write_private


def denied(call):
    try:
        call()
        return False
    except urllib.error.HTTPError as exc:
        return exc.code in (401, 403)
    except RuntimeError as exc:
        return str(exc) == "qBittorrent authentication failed"


def verify():
    result = {"at": datetime.now(timezone.utc).isoformat(), "checks": {}}
    checks = result["checks"]
    q_info = container("qbittorrent")
    ab_info = container("autobangumi")
    checks["qbittorrent_healthy"] = q_info["State"]["Health"]["Status"] == "healthy"
    checks["autobangumi_healthy"] = ab_info["State"]["Health"]["Status"] == "healthy"
    q_ports = q_info["HostConfig"]["PortBindings"] or {}
    ab_ports = ab_info["HostConfig"]["PortBindings"] or {}
    config = settings()
    qb_key = config["QB_WEB_PORT"] + "/tcp"
    peer_keys = {config["PEER_PORT"] + "/tcp", config["PEER_PORT"] + "/udp"}
    checks["admin_ports_loopback_only"] = (
        set(q_ports) == peer_keys | {qb_key}
        and set(ab_ports) == {"7892/tcp"}
        and all(b["HostIp"] == "127.0.0.1" for b in q_ports[qb_key] + ab_ports["7892/tcp"])
    )
    checks["peer_bindings_ipv4_only"] = all(
        b["HostIp"] == "0.0.0.0" for k in peer_keys for b in q_ports[k]
    )
    checks["credentials_private"] = (
        stat.S_IMODE((data_dir() / "secrets/credentials.json").stat().st_mode) == 0o600
    )
    for service, protected in [
        ("qbittorrent", "/api/v2/app/preferences"),
        ("autobangumi", "/api/v1/config/get"),
    ]:
        checks[service + "_anonymous_api_denied"] = denied(lambda: API(service).request(protected))
        checks[service + "_factory_password_denied"] = denied(
            lambda: API(service, {"username": "admin", "password": "adminadmin"}).login()
        )
    qb = API("qbittorrent").login()
    ab = API("autobangumi").login()
    try:
        checks["qbittorrent_version"] = (
            qb.request("/api/v2/app/version", raw=True) == "v" + versions()["qbittorrent"]
        )
        checks["autobangumi_version"] = (
            ab.request("/health")["version"] == versions()["autobangumi"]
        )
        checks["downloader_authenticated"] = ab.request("/api/v1/check/downloader") is True
        preferences = qb.preferences()
        checks["csrf_enabled"] = preferences["web_ui_csrf_protection_enabled"]
        checks["host_check_enabled"] = preferences["web_ui_host_header_validation_enabled"]
        checks["auth_bypasses_disabled"] = not (
            preferences["bypass_local_auth"] or preferences["bypass_auth_subnet_whitelist_enabled"]
        )
        checks["proxy_trust_scoped"] = (
            preferences["web_ui_reverse_proxies_list"] == settings()["PROXY_ADDRESS"]
        )
        bad_host = urllib.request.Request(qb.base + "/", headers={"Host": "untrusted.invalid"})
        checks["bad_host_rejected"] = denied(lambda: qb.opener.open(bad_host, timeout=10))
        bad_origin = urllib.request.Request(
            qb.base + "/api/v2/app/setPreferences",
            method="POST",
            data=b"json=%7B%7D",
            headers={
                "Origin": "https://untrusted.invalid",
                "Referer": "https://untrusted.invalid/",
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        checks["bad_origin_mutation_rejected"] = denied(
            lambda: qb.opener.open(bad_origin, timeout=10)
        )
        result["torrent_count"] = len(qb.torrents())
        config = ab.request("/api/v1/config/get")
        checks["backfill_disabled"] = config["bangumi_manage"]["eps_complete"] is False
        checks["automatic_media_deletion_disabled"] = (
            config["bangumi_manage"]["remove_bad_torrent"] is False
        )
        checks["revision_hold"] = config["bangumi_manage"]["revision_conflict_policy"] == "hold"
        checks["mcp_ip_bypass_disabled"] = not config["security"]["mcp_whitelist"]
    finally:
        qb.logout()
        ab.logout()
    result["passed"] = all(checks.values())
    write_private(data_dir() / "ops/acceptance.json", result)
    print(json.dumps(result, indent=2))
    if not result["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    verify()
