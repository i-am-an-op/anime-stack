#!/usr/bin/env python3
"""Render reviewable Cloudflare API payloads. Makes no network requests."""

import argparse
import json
import re
from pathlib import Path


def payloads(settings):
    zone = settings["zone"]
    hosts = [settings["autobangumi_hostname"], settings["qbittorrent_hostname"]]
    if len(set(hosts)) != 2:
        raise ValueError("The application hostnames must differ")
    for host in [zone, *hosts]:
        if not re.fullmatch(r"[a-z0-9]+(?:[.-][a-z0-9]+)*", host):
            raise ValueError("Use plain lowercase DNS hostnames")
    if not all(host.endswith("." + zone) for host in hosts):
        raise ValueError("Both hostnames must be within the selected zone")
    if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", settings["allowed_email"]):
        raise ValueError("Provide the owner's exact email")
    mfa = {
        "mfa_disabled": False,
        "allowed_authenticators": ["security_key", "biometrics", "totp"],
        "session_duration": "8h",
    }
    output = {
        "01-owner-policy.json": {
            "name": "Anime stack owner",
            "decision": "allow",
            "include": [{"email": {"email": settings["allowed_email"]}}],
            "exclude": [],
            "require": [],
            "mfa_config": mfa,
            "session_duration": "8h",
        },
        "04-create-tunnel.json": {"name": "anime-stack", "config_src": "cloudflare"},
        "06-cache-bypass-rule.json": {
            "description": "Anime stack administration: bypass cache",
            "expression": "(http.host in {" + " ".join(json.dumps(h) for h in hosts) + "})",
            "action": "set_cache_settings",
            "action_parameters": {"cache": False},
            "enabled": True,
        },
    }
    ingress = []
    for number, service, host, port, aud in [
        (2, "autobangumi", hosts[0], 7892, settings["autobangumi_aud"]),
        (
            3,
            "qbittorrent",
            hosts[1],
            int(settings.get("qbittorrent_port", 8080)),
            settings["qbittorrent_aud"],
        ),
    ]:
        output[f"{number:02d}-{service}-access-app.json"] = {
            "name": f"Anime stack {service}",
            "type": "self_hosted",
            "domain": host,
            "destinations": [{"type": "public", "uri": host}],
            "session_duration": "8h",
            "app_launcher_visible": True,
            "http_only_cookie_attribute": True,
            "same_site_cookie_attribute": "lax",
            "enable_binding_cookie": True,
            "allow_authenticate_via_warp": False,
            "options_preflight_bypass": False,
            "mfa_config": mfa,
            "policies": [{"id": settings["policy_id"], "precedence": 1}],
        }
        ingress.append(
            {
                "hostname": host,
                "service": f"http://{service}:{port}",
                "originRequest": {
                    "access": {"required": True, "teamName": settings["team_name"], "audTag": [aud]}
                },
            }
        )
        output[f"07-{service}-dns.json"] = {
            "type": "CNAME",
            "name": host,
            "content": settings["tunnel_id"] + ".cfargotunnel.com",
            "proxied": True,
            "ttl": 1,
        }
    output["05-tunnel-configuration.json"] = {
        "config": {"ingress": [*ingress, {"service": "http_status:404"}]}
    }
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("settings")
    parser.add_argument("output_directory")
    args = parser.parse_args()
    output = Path(args.output_directory)
    output.mkdir(parents=True, exist_ok=True)
    for name, value in payloads(json.loads(Path(args.settings).read_text())).items():
        (output / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n")
    print("Rendered Cloudflare payloads; replace response-dependent IDs before applying.")
