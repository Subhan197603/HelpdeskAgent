# Fusion AI Helpdesk

This repository contains the modular-monolith scaffold, approved initial PostgreSQL physical baseline, and FastAPI application foundation for the Fusion AI Helpdesk described in [BUILD_SPEC.md](BUILD_SPEC.md). Business behavior remains deferred.

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

`make up` starts PostgreSQL, Redis, MinIO, Mailpit, and ClamAV. Check status with `docker compose ps`. The worker and web services remain placeholders. Start the API locally with `make api` or in Compose with `docker compose --profile application up -d --build --wait api`.

Install the physical database baseline once into a clean local database:

```sh
make db-install
make db-validate-baseline
make db-stamp-baseline
make migrate
make db-test
```

Optional demo configuration and the demo ticket remain separate:

```sh
make db-demo-bootstrap
make db-demo-ticket
```

Developer identity is separately opt-in. After migrations, run `make seed`, set
`DEVELOPER_IDENTITY_ENABLED=true` only in a local development `.env`, and use the documented
selectors. See [the developer identity guide](docs/operations/developer-identity.md).

Production bearer authentication uses exact OIDC issuer/audience validation and server-managed
tenant mappings. See [the OIDC operations guide](docs/operations/oidc-authentication.md) before
enabling it or provisioning external identities.

See [the baseline README](database/baseline/fusion_helpdesk_postgres/README.md) for reset safeguards, direct `psql` usage, and the baseline/Alembic boundary.

Local service endpoints:

| Service             | Endpoint                                          |
| ------------------- | ------------------------------------------------- |
| PostgreSQL          | `localhost:5432`                                  |
| Redis               | `localhost:6379`                                  |
| MinIO API / console | `http://localhost:9000` / `http://localhost:9001` |
| Mailpit SMTP / UI   | `localhost:1025` / `http://localhost:8025`        |
| ClamAV              | `localhost:3310`                                  |
| API                 | `http://localhost:8000`                           |

Host ports can be changed in `.env` when a recommended port is already occupied; container-to-container URLs remain unchanged.

## Quality checks

```sh
make format
make lint
make typecheck
make test
make test-integration
```

CI runs the same checks, validates the Compose model, installs and adopts the baseline in isolated PostgreSQL 16/pgvector databases, scans for secrets, and scans the source and API image for vulnerabilities. API details are in [the foundation operations guide](docs/operations/api-foundation.md); migration operations are in [the database migration guide](docs/operations/database-migrations.md).

## Security notes

- Never commit `.env` or real credentials.
- Oracle document acquisition is disabled by default and must remain disabled without recorded permission.
- Local ports are bound to loopback only.
- Runtime data is stored in named Docker volumes and excluded from source control.
