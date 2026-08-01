# Fusion AI Helpdesk

This repository is the modular-monolith scaffold for the Fusion AI Helpdesk described in [BUILD_SPEC.md](BUILD_SPEC.md). Milestone 0, Task 0.1 provides development tooling and local dependency infrastructure only; application and business behavior are intentionally deferred.

## Prerequisites

- Git
- Docker Desktop or another Docker Compose-compatible runtime
- Python 3.12 or newer
- [uv](https://docs.astral.sh/uv/)
- Node.js 22 or newer
- pnpm 10 or newer
- GNU Make (optional; the underlying commands can be run directly on Windows)

## Bootstrap

```sh
make bootstrap
make up
```

`bootstrap` installs locked Python and JavaScript development dependencies and creates a local `.env` from `.env.example` only when one does not already exist. Replace all placeholder credentials before using a shared environment.

`make up` starts PostgreSQL, Redis, MinIO, Mailpit, and ClamAV. Check status with `docker compose ps`. The `api`, `worker`, and `web` services are declared under the `application` Compose profile but remain placeholders until their respective foundation tasks.

Local service endpoints:

| Service             | Endpoint                                          |
| ------------------- | ------------------------------------------------- |
| PostgreSQL          | `localhost:5432`                                  |
| Redis               | `localhost:6379`                                  |
| MinIO API / console | `http://localhost:9000` / `http://localhost:9001` |
| Mailpit SMTP / UI   | `localhost:1025` / `http://localhost:8025`        |
| ClamAV              | `localhost:3310`                                  |

Host ports can be changed in `.env` when a recommended port is already occupied; container-to-container URLs remain unchanged.

## Quality checks

```sh
make format
make lint
make typecheck
make test
```

The CI skeleton runs the same checks, validates the Compose model, scans for secrets, and performs a filesystem vulnerability scan. Database baseline, migrations, application health endpoints, and end-to-end tests belong to later tasks and are called out explicitly by their Make targets.

## Security notes

- Never commit `.env` or real credentials.
- Oracle document acquisition is disabled by default and must remain disabled without recorded permission.
- Local ports are bound to loopback only.
- Runtime data is stored in named Docker volumes and excluded from source control.
