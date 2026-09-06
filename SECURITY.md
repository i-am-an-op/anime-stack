# Security policy

Security fixes target the latest released repository version. Older image pins may remain vulnerable until reviewed and upgraded; this project does not automatically patch application containers.

Report vulnerabilities privately through [GitHub's vulnerability reporting form](https://github.com/i-am-an-op/anime-stack/security/advisories/new). Include the affected release, a minimal reproduction and impact. Do not include live credentials or personal data. Do not post exploitable details in a public issue before a fix or coordinated disclosure.

## Deployment boundaries

- Admin ports bind only to loopback. Use SSH or the documented Access-protected tunnel; never publish a raw admin port as a shortcut.
- AutoBangumi's factory login exists briefly during private startup. Keep the tunnel disabled until bootstrap succeeds.
- Application credentials and the connector token are files with restricted permissions. Compose secrets are mounts, not encryption at rest.
- Keep management API tokens separate from deployment `.env`, and revoke temporary tokens after setup. Only the tunnel-specific token belongs on the server.
- Keep the backup decryption identity off-server. State backups contain credentials and sessions and must stay encrypted outside private recovery work.
- qBittorrent and AutoBangumi use their upstream entrypoints, which initialize ownership with container root privileges. The connector drops capabilities and uses a read-only filesystem. No service receives the Docker socket.
- The guard is a best-effort monitor. Cron outages, unrelated disk writers, force-started torrents and unknown magnet sizes limit its guarantees.

Before publishing a fork, inspect staged files and the complete Git history. `.gitignore` does not remove already committed secrets. Never share `.env`, runtime directories, logs, screenshots containing tokens, restored databases, account-specific Cloudflare payloads or backup keys. GitHub secret scanning and CI reduce risk but do not replace review.
