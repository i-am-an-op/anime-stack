# Deployment guide

## Platform support

The supported baseline is a local, rootful Linux Docker Engine 28+ with Compose 2.24+, Python 3.12+, GNU utilities and a non-root deployment account. Both pinned application images and the connector publish Linux amd64 and arm64 variants. Native amd64 deployment has been exercised with custom ports and external state/media directories; CI tests amd64 and arm64 using disposable Ubuntu runners.

Docker is installed using the distributor-specific procedure from [Docker's installation guide](https://docs.docker.com/engine/install/). Python and cron come from your distribution or another maintained installation. The scripts do not elevate privileges, install packages, open provider firewalls or modify SSH.

| Environment | Status |
| --- | --- |
| Debian/Ubuntu Linux on amd64 | Supported baseline; deployment exercised |
| Other Linux distributions with equivalent prerequisites | Intended to work; verify distribution-specific ownership, firewall and scheduling |
| Linux arm64 | Images available; native CI covers the template |
| SELinux-enforcing hosts | Apply an appropriate container file label to dedicated data paths; do not disable SELinux globally |
| NAS appliance container interfaces | Manual adaptation may be needed; use the appliance's supported Docker/storage mechanisms |
| Rootless Docker or user namespace remapping | Preflight rejects these until ownership and networking are separately validated |
| Remote Docker contexts | Unsupported by host scripts; run them on the actual server over SSH |
| Windows/macOS Docker Desktop | Linux images may run, but this host automation and cron workflow are not supported natively |

“Portable” means configurable deployment across compatible hosts, not a guarantee for every kernel, filesystem or container platform. Swarm, Kubernetes and Podman are not tested targets.

## Configuration

`manage.py init` generates `.env` only when missing. It never sources it as shell code and rejects expansion syntax. The current numeric UID/GID is written automatically. Runtime data is separate from source; existing state and passwords are preserved. Initialization refuses to recreate credentials if it finds orphaned application state.

Use literal unquoted values, without `$`, backticks or `~`. Paths can be absolute or relative to the repository. Prefer dedicated local filesystems; SQLite state must support normal locking and durable writes. Keep management API tokens out of this file.

| Variable | Default | Purpose |
| --- | --- | --- |
| `COMPOSE_PROJECT_NAME` | `anime-stack` | Isolates container/network names and cron entries |
| `PUID`, `PGID` | Detected at initialization | Owner of application files; match the invoking account |
| `TZ` | `Etc/UTC` | Container timezone; cron still follows host time |
| `DATA_DIR` | `./runtime` | State, credentials, guard records, policy and encrypted backups |
| `MEDIA_DIR` | `./runtime/media` | qBittorrent's `/downloads` mount; completed files in `Bangumi` |
| `QB_WEB_PORT` | `8080` | qBittorrent's internal and loopback host WebUI port |
| `AB_WEB_PORT` | `7892` | Loopback host port; AutoBangumi's internal port remains 7892 |
| `PEER_PORT` | `50888` | Same public IPv4 TCP/UDP peer port inside and outside qBittorrent |
| `NETWORK_SUBNET` | `172.28.100.0/24` | Dedicated non-overlapping RFC1918 subnet |
| `QB_ADDRESS`, `AB_ADDRESS`, `PROXY_ADDRESS` | `.2`, `.3`, `.4` in that subnet | Application addresses and the narrowly trusted connector address |
| `QB_PUBLIC_HOST`, `AB_PUBLIC_HOST` | Empty | Optional domain names; configure Access before publishing |

Change all network addresses together when changing the subnet. Preflight detects overlapping Docker networks, but also review host LAN, VPN and provider routes. Docker reserves the first usable address for the gateway. A second stack needs a unique project name, subnet, three ports and data/media paths.

For external storage, mount the filesystem first and set paths before initialization, for example `DATA_DIR=/srv/anime-state` and `MEDIA_DIR=/mnt/media/anime`. Run initialization again after editing `.env` to create missing dedicated directories. Do not point `DATA_DIR` at the source directory or a directory containing unrelated state. If storage goes missing, bind mounts are configured to reject absent source paths instead of silently creating replacement state directories.

The bootstrap step updates AutoBangumi's downloader hostname/port while preserving other API configuration. Existing password changes still require coordinated credential updates; see the operations guide.

## Networking

The host scripts use local loopback HTTP. Application credentials remain required there. SSH protects remote access. Use the qBittorrent WebUI port itself on both ends of forwarding because Host-header validation checks the requested port.

Docker Engine 28+ is required because older versions had documented limitations around localhost-bound published ports. See [Docker's port-publishing guidance](https://docs.docker.com/engine/network/port-publishing/). Treat other local host users as trusted administrators of the deployment account.

Peer traffic uses the configured public IPv4 port. Check provider terms, egress quotas, NAT and both host/provider firewalls. Docker-published ports can interact differently with firewall frontends than ordinary host services. No IPv6 peer publication or inbound 80/443 listener is created by the template. Cloudflare needs outbound connectivity as described in its guide.

## Capacity and policy

On first initialization, stop space is 10% of free media space, bounded to 1–25 GiB. Warning space is approximately 20%, capped at 40 GiB and above the stop threshold. The soft media budget uses the remaining initial free space. These are starting values, written once to `DATA_DIR/policy.json`; they do not automatically track later disk expansion.

Download/upload limits start at 20/2 MiB/s with two active downloads and three uploads. The guard requires bounded normal and alternate download limits and queueing. Modify the runtime policy deliberately and rerun bootstrap with `manage.py up` to apply it. Changing limits in the UI alone can trigger a hold when they exceed policy.

Size media from expected episode size × episode count × shows retained, plus reserve, temporary changes and other disk users. For example, 10 shows × 12 episodes × 1.5 GiB is 180 GiB before reserve. A 4K-capable display does not imply that a release has native 4K detail. Retention is manual; there is no automatic media purge.
