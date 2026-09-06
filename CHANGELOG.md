# Changelog

Changes follow [Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-09-06

### Added

- Portable Docker Compose deployment of pinned qBittorrent, AutoBangumi and optional cloudflared images.
- Private bootstrap with generated credentials, configurable paths/network/ports, and prerequisite checks.
- Persistent disk-pressure holds and opt-in cron scheduling.
- Age-encrypted state backups and guarded recovery into a new directory, including SQLite WAL state.
- Cloudflare Access/MFA setup instructions and per-application JWT-validating tunnel payloads.
- Operational, security, troubleshooting and contribution guides with automated validation.
