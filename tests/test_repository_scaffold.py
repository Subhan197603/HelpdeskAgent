from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_SERVICES = {
    "postgres",
    "redis",
    "minio",
    "minio-init",
    "clamav",
    "mailpit",
    "api",
    "worker",
    "web",
}
HEALTH_CHECKED_SERVICES = {"postgres", "redis", "minio", "mailpit", "clamav"}


def test_required_repository_files_exist() -> None:
    required_files = {
        ".editorconfig",
        ".env.example",
        ".gitignore",
        "BUILD_SPEC.md",
        "Makefile",
        "README.md",
        "docker-compose.yml",
        "package.json",
        "pnpm-workspace.yaml",
        "pyproject.toml",
    }

    assert all((ROOT / path).is_file() for path in required_files)


def test_compose_declares_required_services_and_health_checks() -> None:
    compose = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]

    assert services.keys() >= REQUIRED_SERVICES
    assert all("healthcheck" in services[name] for name in HEALTH_CHECKED_SERVICES)


def test_oracle_document_acquisition_is_disabled_by_default() -> None:
    environment = (ROOT / ".env.example").read_text(encoding="utf-8").splitlines()

    assert "ORACLE_DOCUMENT_ACQUISITION_ENABLED=false" in environment
