# BaumLabBackup

A self-hosted Docker backup manager with a dark-themed web UI.

## Features

- **Backup Scheduling** — Cron-based scheduling via APScheduler
- **Docker Integration** — Stop/start containers around backups, volume copying
- **Database Dumps** — MySQL and PostgreSQL dump support
- **Multiple Destinations** — Backblaze B2, SMB/NAS, SFTP, Local storage via rclone
- **Encryption** — Credentials encrypted at rest with Fernet (PBKDF2 key from SECRET_KEY)
- **Authentication** — JWT with optional TOTP/MFA
- **Retention** — Automatic cleanup of old backups via rclone
- **Web UI** — Dark-themed single-page app: dashboard, jobs, destinations, history, settings

## Quick Start

1. Copy `.env.example` to `.env` and fill in values:

```bash
cp .env.example .env
# Edit .env:
# SECRET_KEY=$(openssl rand -hex 32)
# ADMIN_PASSWORD=your_secure_password
```

2. Start the stack:

```bash
docker compose up -d
```

3. Open [http://localhost:8765](http://localhost:8765) and log in as `admin`.

## Configuration

| Variable | Description | Default |
|---|---|---|
| `SECRET_KEY` | Secret for JWT + encryption (required) | — |
| `ADMIN_PASSWORD` | Admin password on first start | — |
| `WEB_PORT` | Host port for the web UI | `8765` |
| `TZ` | Container timezone | `America/New_York` |

## Destinations

### Backblaze B2
Requires an Application Key with read/write access to the target bucket.

### SMB / NAS
Network share (Windows share / Samba). Provide host, share name, credentials.

### SFTP
SSH file transfer. Supports password or key-file authentication.

### Local
Local path inside the container (mount an external path into the container as needed).

## Security Notes

- All destination credentials are encrypted in the database using Fernet symmetric encryption.
- The `SECRET_KEY` env var is used to derive the encryption key — keep it safe and back it up.
- The Docker socket is mounted read-only for container listing; write access is needed for stop/start — adjust the compose file if you only need listing.
- TOTP/MFA can be enabled per-user from the Settings page.

## License

MIT
