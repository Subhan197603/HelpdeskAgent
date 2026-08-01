# Local development

Run `make bootstrap` once, then `make up` to start local dependencies. Use `docker compose ps` to inspect health and `make logs` for service logs.

The checked-in environment file contains placeholders only. A local `.env` is ignored by Git and must not contain production credentials.
