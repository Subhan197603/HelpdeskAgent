# Local development security

- Dependency ports bind only to `127.0.0.1`.
- Local credentials in `.env.example` are placeholders and are not suitable for shared environments.
- Application placeholders run read-only with `no-new-privileges` when their profile is explicitly enabled.
- Automated Oracle document acquisition is disabled by default.
- Do not place tokens, documents, attachment contents, or personally identifiable information in logs.
