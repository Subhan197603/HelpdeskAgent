# Local development

Run `make bootstrap` once, then `make up` to start local dependencies. Use `docker compose ps` to inspect health and `make logs` for service logs.

The checked-in environment file contains placeholders only. A local `.env` is ignored by Git and must not contain production credentials.

## PostgreSQL baseline

The baseline SQL is mounted read-only at `/baseline` in the PostgreSQL container. This means installation uses the container's `psql` and does not depend on the published host port:

```sh
make db-install
make db-test
```

Set `POSTGRES_HOST_PORT` in `.env` if port 5432 is occupied. Container-to-container traffic continues to use port 5432.

Demo data is opt-in:

```sh
make db-demo-bootstrap
make db-demo-ticket
```

Reset is destructive and restricted to the fixed local `helpdesk` database. It requires both safeguards:

```sh
make db-reset APP_ENV=development CONFIRM_DB_RESET=local-helpdesk
```

Never use `db-reset` for shared or production databases. Named Docker volumes are not removed by this target.

`make db-install` also provisions the fixed `helpdesk` login as a member of the baseline's
non-owner `helpdesk_app` role. Its password is a local-only placeholder controlled by
`POSTGRES_APP_PASSWORD`; production role and secret provisioning is external.

## API

See [API foundation operations](api-foundation.md) for host and Compose startup, health endpoint
semantics, correlation IDs, structured logging, pool configuration, and transaction boundaries.
