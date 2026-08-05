"""Contract tests for the knowledge article reader (Task 11.4)."""

from typing import Any, cast

from fastapi.testclient import TestClient

LIST_PATH = "/api/v1/knowledge/articles"
DETAIL_PATH = "/api/v1/knowledge/articles/{document_id}"


def _contract(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", client.get("/openapi.json").json())


def _schemas(client: TestClient) -> dict[str, Any]:
    return cast("dict[str, Any]", _contract(client)["components"]["schemas"])


def test_article_list_contract_exposes_articles_facets_and_paging(
    client: TestClient,
) -> None:
    operation = _contract(client)["paths"][LIST_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("KnowledgeArticleListResponse")
    parameters = {parameter["name"] for parameter in operation.get("parameters", [])}
    assert {"persona", "document_type", "limit", "offset"} <= parameters
    schemas = _schemas(client)
    response_properties = schemas["KnowledgeArticleListResponse"]["properties"]
    for field in ("items", "facets", "has_more"):
        assert field in response_properties, field
    summary_properties = schemas["KnowledgeArticleSummary"]["properties"]
    for field in (
        "id",
        "title",
        "document_type",
        "source_type",
        "source_name",
        "excerpt",
        "language_code",
        "product_name",
        "release_code",
        "audience_code",
        "published_at",
        "updated_at",
    ):
        assert field in summary_properties, field
    facet_properties = schemas["KnowledgeArticleFacet"]["properties"]
    for field in ("document_type", "count"):
        assert field in facet_properties, field


def test_article_detail_contract_exposes_metadata_and_sections(
    client: TestClient,
) -> None:
    operation = _contract(client)["paths"][DETAIL_PATH]["get"]
    reference = operation["responses"]["200"]["content"]["application/json"]["schema"]["$ref"]
    assert reference.endswith("KnowledgeArticleDetailResponse")
    schemas = _schemas(client)
    detail_properties = schemas["KnowledgeArticleDetailResponse"]["properties"]
    for field in (
        "id",
        "title",
        "document_type",
        "source_type",
        "source_name",
        "audience_code",
        "security_classification",
        "language_code",
        "product_name",
        "release_code",
        "canonical_url",
        "owner_group_name",
        "policy_owner",
        "process_owner",
        "version_number",
        "published_at",
        "updated_at",
        "next_review_date",
        "sections",
    ):
        assert field in detail_properties, field
    section_properties = schemas["KnowledgeArticleSection"]["properties"]
    for field in ("heading_path", "section_title", "section_anchor", "page_number", "content"):
        assert field in section_properties, field


def test_article_endpoints_require_authentication(client: TestClient) -> None:
    assert client.get(LIST_PATH).status_code == 401
    detail = client.get(DETAIL_PATH.format(document_id="00000000-0000-0000-0000-000000000001"))
    assert detail.status_code == 401


def test_article_contracts_expose_no_storage_or_processing_internals(
    client: TestClient,
) -> None:
    schemas = _schemas(client)
    for schema_name in ("KnowledgeArticleSummary", "KnowledgeArticleDetailResponse"):
        properties = schemas[schema_name]["properties"]
        for forbidden in (
            "original_file_uri",
            "normalized_file_uri",
            "quarantine_object_key",
            "sha256_checksum",
            "object_key",
            "embedding",
            "processing_versions",
        ):
            assert forbidden not in properties, f"{schema_name}.{forbidden}"
