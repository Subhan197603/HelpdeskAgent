# Security test plan and findings register

Task 10.2 formalizes the security validation that runs on every change and records the current
findings status. Scope: the Fusion AI Helpdesk monorepo — API, worker, web, database, container
images, and AI surfaces.

## Automated security controls (run in CI on every push/PR)

| Control                                              | Tool                                     | Location                                                           | Failure policy        |
| ---------------------------------------------------- | ---------------------------------------- | ------------------------------------------------------------------ | --------------------- |
| Secret scanning (history + tree)                     | gitleaks                                 | CI `secret-scan` job                                               | fail build            |
| Python dependency vulnerabilities                    | pip-audit                                | CI `quality` job                                                   | fail build            |
| JS dependency vulnerabilities                        | pnpm audit `--audit-level high`          | CI `quality` job                                                   | fail on high/critical |
| Filesystem vulnerability/misconfig scan              | Trivy fs (CRITICAL,HIGH, ignore-unfixed) | CI `vulnerability-scan` job                                        | fail build            |
| API and web image scans                              | Trivy image (CRITICAL,HIGH)              | CI `vulnerability-scan` job                                        | fail build            |
| Identity / OIDC / RLS regression                     | pytest integration suites                | `tests/integration/test_identity_authorization.py`, `test_oidc.py` | fail build            |
| Tenant-isolation and authorization penetration cases | pytest                                   | `tests/integration/test_security_regression.py`                    | fail build            |
| Retrieval ACL regression                             | pytest                                   | retrieval regression corpus (Task 7.3)                             | fail build            |
| AI safety thresholds                                 | pytest                                   | `tests/ai_evaluation/test_agent_thresholds.py`                     | fail build            |
| Prompt-injection and malicious-content handling      | pytest                                   | employee-agent and copilot suites                                  | fail build            |
| Append-only history protection                       | pytest + DB grants/triggers              | migration and integration suites                                   | fail build            |

## Penetration case inventory

Executed as deterministic tests in `tests/integration/test_security_regression.py`:

1. Cross-tenant analyst enumeration — tenant B agent listing excludes tenant A tickets.
2. Cross-tenant direct object reference — tenant A ticket key returns 403/404 for tenant B.
3. Cross-tenant timeline and copilot access — 404; no AI context leaves the tenant.
4. Cross-tenant write attempt — internal comment on foreign ticket rejected; no row written.
5. Vertical privilege escalation — customer denied analyst queues, ticket lists, copilot,
   AI-oversight metrics and evaluation dataset.
6. Authentication bypass — missing header 401; unknown subject 401; valid subject under the
   wrong tenant code 401; denials recorded in `audit.security_event`.
7. Positive control — same-tenant analyst retains authorized access (guards against
   over-restriction masking broken tests).

Complementary standing cases: pooled-connection identity leakage (identity suite), RLS
enforcement as non-owner role (baseline/identity suites), reporting-role isolation
(`tests/integration/test_reporting.py`), attachment quarantine (Task 4.4 suite), and tool
authorization (`ai.tool_call` audit assertions in copilot suites).

## Manual review cadence

- Threat-model and permission-matrix review at each milestone approval (orchestrator gate).
- Dependency-update review when audits report new advisories.
- Production penetration test by an external assessor before go-live sign-off (Task 10.3
  readiness item).

## Findings register

| ID           | Finding                                                       | Severity      | Status   | Owner                | Notes                                                                                                                                                                                  |
| ------------ | ------------------------------------------------------------- | ------------- | -------- | -------------------- | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| SEC-2026-001 | 3 moderate advisories in JS dev-dependency chain (pnpm audit) | Moderate      | Accepted | Platform engineering | Dev-time tooling only; not shipped in the web image (verified by Trivy image scan). Re-evaluated on every dependency bump; upgrade when upstream releases fixes. Review by 2026-09-30. |
| SEC-2026-002 | Starlette TestClient deprecation warning (httpx pin)          | Informational | Accepted | Platform engineering | Test-only surface; tracked with framework upgrade train.                                                                                                                               |

No open critical or high findings. Any new critical/high finding blocks release until resolved
or formally accepted here with owner and review date.
