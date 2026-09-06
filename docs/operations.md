# Operations and recovery

All commands run from the repository directory on the server unless stated otherwise. Examples assume `DATA_DIR=./runtime`; substitute your configured directory.

## Disk guard

The guard measures free media space, allocated media bytes and remaining selected torrent payloads, including stopped or queued incomplete tasks. It verifies that normal and alternate download limits and queueing remain bounded by policy. Magnet sizes are unknown until metadata arrives.

A low-space condition, an oversized queue or failed monitoring persists a hold and stops both application containers. The stop also pauses torrents through the API when possible. Cloudflared and SSH remain available. The guard re-enforces a hold after restart and never deletes media or clears the hold itself.

```sh
python3 scripts/guard.py status
python3 scripts/guard.py hold
python3 scripts/guard.py resume
```

To resume, recover at least the warning threshold, remove unwanted queued tasks if necessary and inspect the policy. Explicit resume restarts the applications and leaves existing torrents stopped for you to select. Do not bypass a hold with `docker compose up`.

`runtime/ops/guard-status.json` is the latest sample; `runtime/ops/hold.json` is the latch. The cron entry runs every minute and logs warnings/errors under the project-specific guard tag. Verify the timestamp advances without an SSH session. A configured crontab is ineffective if the cron daemon is stopped. The guard and backups share a lock so expected backup downtime does not trigger a false monitoring failure.

There is no external alert delivery. Add your own monitored notification destination if required. Force-started torrents, unrelated disk writers, filesystem behavior, failed cron and unresponsive processes mean this monitor cannot guarantee a hard quota.

## Encrypted backups

Install [age](https://github.com/FiloSottile/age) using a maintained package or a verified upstream release. On a **trusted machine outside the server**, create an identity and obtain its public recipient:

```sh
age-keygen -o backup-identity.txt
age-keygen -y backup-identity.txt
```

Keep `backup-identity.txt` private and retain a separate protected copy. Copy only the public `age1...` recipient line to `runtime/backup-recipient.txt` on the server. The scripts require `age` on the server's PATH; the server does not need the private identity.

```sh
python3 scripts/backup.py create
python3 scripts/install_jobs.py --with-backup
```

The scheduled backup runs daily at 04:17 **host time**. It briefly stops the applications, streams a consistent archive directly through age, then restarts only applications that were previously running unless a hold is active. Seven encrypted state archives are retained by default, according to the runtime policy.

The snapshot includes source/runbooks, `.env`, state, credentials, the connector token, optional Cloudflare resource records, the bootstrap marker and any hold. Media, the age private key, Docker metadata, compiled Python caches and AutoBangumi's regenerable `.ab_owner` marker are excluded. Configuration/state from an external `DATA_DIR` is normalized under `runtime/` inside the archive.

Backups are written to `runtime/backups/state-*.tar.gz.age`. Copy them off-server manually or configure a separate trusted backup destination. The included scheduler only stages archives locally. Keep backup failure monitoring in your operational routine.

## Restore

On a trusted recovery machine, decrypt a selected archive and restore into a **new directory**:

```sh
age --decrypt -i backup-identity.txt -o state.tar.gz state-TIMESTAMP.tar.gz.age
python3 scripts/backup.py restore state.tar.gz --to /path/to/new-restored-stack
```

The restore command rejects existing targets, traversal paths, links, special files and unexpected archive entries. It resets the restored `.env` to local runtime/media paths and an `anime-stack-recovery` project name, saving the original `.env` privately under `runtime/recovery/`. It preserves an existing hold or creates a new review hold. It never starts containers.

Before running the restored stack:

1. Check the image pins, UID/GID, ownership, paths, available space, unique ports and a non-overlapping subnet. On a replacement host, review the copied disk policy against its capacity.
2. Restore or reattach the matching media separately. Compare qBittorrent resume state with actual files; media is not in the state archive.
3. Check SQLite integrity with **the entire restored AutoBangumi data directory**, including `data.db-wal` and `data.db-shm` when present. The main database alone may contain no schema because committed data remains in the WAL.
4. Run `manage.py check`, inspect the hold, and use `guard.py resume` only when ready. Initially use private SSH access and verify application authentication and the downloader connection.
5. Reinstall cron jobs and age/public-recipient configuration. Review Cloudflare account resources before starting the connector. Restore DNS and Access configuration deliberately; a saved JSON record does not recreate cloud resources automatically.
6. Validate a selected real download against its media before relying on the restored setup. Remove temporary decrypted archives and recovery directories when no longer needed.

The automated recovery test verifies extraction, credentials, held state and SQLite/WAL integrity. It does not start a second stack from the recovered copy or prove recovery of media absent from the backup.

## Password changes

Keep SSH available. Stop normal acquisition and take a backup. A qBittorrent password change must be reflected in both AutoBangumi's downloader configuration and `runtime/secrets/credentials.json`; an AutoBangumi login change must match that credentials file too. The guard authenticates with these stored values and will hold the stack if they are stale.

Do not edit credentials through shell arguments or paste them into issues. Use a private editor/secret workflow, preserve file mode 0600, then verify both application logins, the internal downloader connection and the guard. Bootstrap is not a credential-reset tool for unknown existing state.

## Manual SFTP, retention and seeding

Use your SSH key and a verified host key. Copy completed, finally renamed files from `MEDIA_DIR/Bangumi` to the playback PC, including sidecar subtitles/fonts. For a stable copy, stop the selected completed torrent and pause processing while copying. Verify local playback before removing the server data.

Delete deliberately through the appropriate qBittorrent task-and-files action. Removing a rule or archiving a show in AutoBangumi is not the same as reclaiming disk space. Avoid accidentally making old items eligible for rediscovery. There is no scheduled media deletion.

Configure seeding limits appropriate to your provider and sources. Initial bandwidth limits are not a traffic quota; even a modest continuous upload rate can consume a substantial monthly allowance. A guard hold stops seeding as well as downloading.

## Updates and rollback

1. Review upstream release notes and security advisories. Check the exact tag, manifest digest, supported architectures and any database/configuration migration.
2. Take and copy a verified encrypted backup, and record the current repository release.
3. Update `compose.yaml` and `versions.json` together. Review compatibility code and regenerate any affected examples. Pull the pinned images and recreate using `manage.py up`.
4. Verify versions, authentication, downloader connection, guard, backup recovery and an appropriate real release. For public access, also check owner MFA, proxy mutations and event updates.
5. Roll back using the earlier image **and its matching state backup**. An image rollback alone may not reverse a database migration or AutoBangumi's persistent update overlay.

The template intentionally uses neither a floating `latest` tag nor an automatic container updater. Uninstalling containers does not delete your bind-mounted files. Inspect and remove runtime/media directories only when you deliberately intend to erase them.
