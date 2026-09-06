# Anime Stack

[![CI](https://github.com/i-am-an-op/anime-stack/actions/workflows/ci.yml/badge.svg)](https://github.com/i-am-an-op/anime-stack/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](LICENSE)

Deploy **AutoBangumi + qBittorrent** with Docker Compose, track the releases you select, and copy completed episodes to your own player over SFTP. An optional named Cloudflare Tunnel provides web administration behind Access and MFA.

The template starts privately, generates separate strong application passwords, limits download growth, and includes a disk guard and encrypted state backups. It contains no subscriptions, media, server credentials or Cloudflare account configuration.

## Requirements

- A **Linux amd64 or arm64 server**, a non-root account, and a local rootful Docker Engine **28+** with Compose **2.24+**.
- **Python 3.12+** with timezone data; GNU `tar` and `du`. The runtime Python scripts use only the standard library.
- Writable local state storage and enough media space. Start with roughly 2 GiB RAM plus workload headroom; media capacity depends on releases and retention.
- For scheduled protection: an installed, running **cron daemon** and `logger`. For encrypted backups: **age and age-keygen**.

Follow the [official Docker installation instructions](https://docs.docker.com/engine/install/) for your distribution. The helper checks prerequisites; it does not install Docker, change firewall rules or grant host privileges. Docker access is powerful: use a trusted deployment account.

The image indexes include amd64 and arm64. See [platform support and limitations](docs/deployment.md#platform-support) for NAS, SELinux, rootless Docker, remote Docker contexts and Docker Desktop. Native Windows/macOS host automation is not supported.

## Quick start

Run these commands **on the server**, using the account that can access Docker:

```sh
git clone https://github.com/i-am-an-op/anime-stack.git
cd anime-stack
python3 scripts/manage.py init
```

Initialization detects your UID/GID, creates an ignored `.env`, generates credentials, and sizes the initial disk thresholds from free space. Review `.env` for paths, ports, timezone and subnet conflicts. Review `runtime/policy.json` for capacity and bandwidth; `runtime` is the default `DATA_DIR`.

```sh
python3 scripts/manage.py check
python3 scripts/manage.py up
python3 scripts/manage.py verify
python3 scripts/install_jobs.py
```

`up` starts the two applications, replaces AutoBangumi's factory password, verifies the downloader connection and applies the disk policy. If bootstrap fails, it stops both applications. `verify` includes one rejected factory-login attempt per application. `install_jobs.py` schedules the guard every minute; confirm the host cron service is running.

The default administration addresses bind **only to server loopback**. From your PC, forward the matching ports over SSH:

```sh
ssh -N -L 8080:127.0.0.1:8080 -L 7892:127.0.0.1:7892 your-user@your-server
```

Open **http://127.0.0.1:8080** for qBittorrent and **http://127.0.0.1:7892** for AutoBangumi. Read your generated login details from `runtime/secrets/credentials.json` privately. If you change ports, use those same ports in SSH forwarding and browser URLs; qBittorrent validates the requested Host port.

Only the configured peer port (default **50888 TCP/UDP over IPv4**) is public. Provider firewalls and NAT may require separate configuration. [Cloudflare Access](docs/cloudflare.md) is optional; private SSH access works without a domain.

## Start tracking

Add one show and a feed you are authorized to use, choose a release group, preview its matches, and verify completion and renaming before expanding. Chinese subtitles in either writing system are a reasonable first choice, with reviewed raws as a fallback. Prefer source quality over a blanket 2160p filter; many seasonal releases are 1080p.

The default polls RSS every 15 minutes. Automatic historical completion, bad-torrent deletion, revision replacement, LLM parsing and MCP authentication bypasses are disabled. Selecting a season subscription in the UI can still add a backlog; inspect that action before confirming it. No torrents are downloaded by setup or CI.

Copy completed files from **`MEDIA_DIR/Bangumi`** with your SFTP client. Ignore `.!qB` files and wait for AutoBangumi's final rename. Include accompanying subtitles/fonts. Files stay on the server until you remove them deliberately; copying to the PC does not free server storage.

## Operations and recovery

```sh
python3 scripts/manage.py status
python3 scripts/guard.py status
python3 scripts/guard.py hold
python3 scripts/guard.py resume
```

The disk guard counts queued payloads, stops both applications on pressure or monitoring failure, and keeps a persistent hold. It never deletes media or automatically resumes downloads. This is a protective monitor, not a disk quota or a monthly traffic cap.

Set up [encrypted backups and recovery](docs/operations.md#encrypted-backups) before relying on the deployment. Keep the age decryption key off the server, test recovery with the full SQLite directory including WAL files, and copy backups off-server. Scheduling is explicit:

```sh
python3 scripts/backup.py create
python3 scripts/install_jobs.py --with-backup
```

## Documentation

| Guide | Covers |
| --- | --- |
| [Deployment](docs/deployment.md) | Environment variables, prerequisites, storage, platforms and networking |
| [Cloudflare](docs/cloudflare.md) | Owner-only Access, MFA, named Tunnel, JWT validation and cache bypass |
| [Operations](docs/operations.md) | Guard, backups, safe recovery, SFTP, password changes and upgrades |
| [Design and evidence](docs/design.md) | Architecture, tradeoffs, validation scope and primary sources |
| [Troubleshooting](docs/troubleshooting.md) | Startup, login, disk holds, Cloudflare and SQLite |

Pinned application versions are recorded in [versions.json](versions.json); image tags and immutable multi-platform digests are in [compose.yaml](compose.yaml). There are no automatic application updates. Follow the upgrade procedure when changing pins.

Contributions are welcome through pull requests. See [CONTRIBUTING.md](CONTRIBUTING.md), [SECURITY.md](SECURITY.md), and [CHANGELOG.md](CHANGELOG.md). The original scripts and documentation use the [MIT license](LICENSE); referenced containers retain their own upstream licenses.
