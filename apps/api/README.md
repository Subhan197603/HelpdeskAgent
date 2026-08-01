# API application

The API is a FastAPI modular-monolith entry point. Run it from the repository root with
`make api`; set `API_RELOAD=true` only for local development. The ASGI import is
`apps.api.app.main:app`, and code that needs isolated configuration should call
`create_app(settings)`.

Foundation modules own configuration, logging, request context, exception mapping,
dependency probes, database sessions, and explicit units of work. Route modules must not
initialize infrastructure or access arbitrary tables. Business modules and protected routes
begin in later milestones.

See [API foundation operations](../../docs/operations/api-foundation.md) for configuration,
health, transaction, and test details.
