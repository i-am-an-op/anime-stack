# Troubleshooting

## Preflight or startup fails

Run `python3 scripts/manage.py check` on the Docker server. Fix the specific prerequisite, ownership, path, port or subnet error. Run as the account identified by PUID/PGID. Python 3.12+, Docker 28+ and Compose 2.24+ are explicit requirements; a remote Docker context is not equivalent to executing on the server.

If a different service owns a port, choose another in `.env` and rerun initialization/preflight. If a Docker subnet overlaps, change the subnet and all three addresses together. Review host/VPN routes too. If a data disk is missing, remount it; do not create replacement empty directories and continue.

`manage.py up` stops both applications on bootstrap failure. Inspect application state privately, correct the cause and retry. Do not delete databases or reset credentials simply to bypass a failed check. Existing state without its credential file needs recovery from a matching backup.

## Login fails

Use the generated credentials, not the factory password. For SSH forwarding, qBittorrent's browser port must match `QB_WEB_PORT`; its Host check also validates ports. Public domain names go in `.env` and are applied during bootstrap. Keep CSRF and Host validation enabled.

qBittorrent may return an empty HTTP 204 after successful login. Success is determined by a protected API request with the resulting session cookie. HTTP 401 can be its intended CSRF/Host rejection. Repeated intentional bad-login probes can trigger IP bans; run the included acceptance check once per relevant deployment change.

If a password changed, coordinate the local credentials file, AutoBangumi downloader settings and the application account. The disk guard cannot monitor with stale credentials and will stop the applications.

## The guard stopped downloading

Inspect `python3 scripts/guard.py status`. Free space alone may be insufficient if queued/stopped incomplete tasks reserve more data than the available budget. Remove unwanted queue entries or recover space. Check normal and alternate rate limits and queueing against the runtime policy.

The hold is deliberate and persists after recovery. Use `guard.py resume` after correcting the cause; it does not resume existing torrents automatically. Verify the cron status timestamp advances. Do not remove the latch file manually to bypass a failed check.

## Cloudflare login, 403 or 502

- A login redirect for an anonymous request is expected. Verify the exact-owner policy and independent MFA; do not add a bypass rule.
- An API 403 while changing organization MFA indicates a permissions/scope issue. Organization Read cannot enable MFA; use the dashboard or a scoped Edit permission and allow brief propagation.
- Confirm that both application ingress rules require Access and contain the correct **different** audiences. The team value omits `.cloudflareaccess.com`.
- Check the connector token file owner/mode, container readiness and outbound TCP/UDP 7844. Avoid sharing raw logs or token responses.
- For a 502 after owner login, check application health, internal service names/ports, qBittorrent's allowed hostname and the tunnel's effective configuration.
- Test live AutoBangumi updates after login. A working HTML page alone does not verify SSE. Do not use a quick tunnel as a substitute for the named-tunnel setup.

## Backups or SQLite restoration fail

Ensure `age` is installed and the public recipient file contains one `age1...` line. The private identity stays off-server. Check available state/backup space and scheduling logs. A failed or partial backup is not a recovery point.

Restore to a new directory using the supplied command. Include the entire SQLite directory, particularly `data.db-wal` and `data.db-shm`; an integrity check of an isolated empty main database is not proof that the real data was recovered. Validate expected tables and rows as well as integrity.

Restored deployments start held and use local recovery paths. Review `.env`, ownership, ports, subnet, disk policy and matching media before explicit resume. An application image downgrade cannot undo a database migration by itself.
