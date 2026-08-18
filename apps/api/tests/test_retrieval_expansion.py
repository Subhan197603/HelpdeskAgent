"""Governed synonym expansion determinism, gating, and fail-open tests."""

from uuid import UUID

import pytest

from apps.api.app.core.context import RequestContext
from apps.api.app.identity.authorization import AuthorizationService
from apps.api.app.retrieval.expansion import (
    MAX_APPENDED_EXPANSIONS,
    expand_query,
    expansion_tenant_ids,
)
from apps.api.app.retrieval.normalization import MAX_QUERY_CHARACTERS
from apps.api.app.retrieval.service import RetrievalService

from .conftest import make_test_settings

TENANT = UUID("20000000-0000-0000-0000-000000000001")
USER = UUID("22000000-0000-0000-0000-000000000001")


def test_expansion_defaults_are_off() -> None:
    settings = make_test_settings()
    assert settings.retrieval_synonym_expansion_enabled is False
    assert settings.retrieval_synonym_expansion_tenant_ids == ""


def test_tenant_allowlist_parsing_is_bounded_and_normalized() -> None:
    assert expansion_tenant_ids("") == frozenset()
    assert expansion_tenant_ids(" A , b ,, ") == frozenset({"a", "b"})


def test_whole_word_match_appends_expansion() -> None:
    result = expand_query("vpn not working", [("vpn", "virtual private network")])
    assert result.applied is True
    assert result.expanded_term_count == 1
    assert result.search_query == "vpn not working virtual private network"
    assert result.lexical_query == 'vpn not working or "virtual private network"'


def test_partial_token_never_matches() -> None:
    result = expand_query("vpnclient down", [("vpn", "virtual private network")])
    assert result.applied is False
    assert result.search_query == "vpnclient down"
    assert result.lexical_query == "vpnclient down"


def test_multi_word_term_matches_and_duplicates_are_skipped() -> None:
    result = expand_query(
        "single sign on broken",
        [
            ("single sign on", "sso"),
            ("single sign on", "sign on"),
        ],
    )
    assert result.search_query == "single sign on broken sso"
    assert result.expanded_term_count == 1


def test_appended_words_deduplicate_across_entries() -> None:
    result = expand_query(
        "vpn issue",
        [("vpn", "remote tunnel"), ("issue", "tunnel")],
    )
    assert result.search_query == "vpn issue remote tunnel"
    assert result.lexical_query == 'vpn issue or "remote tunnel"'
    assert result.expanded_term_count == 1


def test_expansion_cap_is_enforced_deterministically() -> None:
    entries = [("vpn", f"expansion{index}") for index in range(10)]
    result = expand_query("vpn", entries)
    assert result.expanded_term_count == MAX_APPENDED_EXPANSIONS
    assert result.search_query == "vpn " + " ".join(
        f"expansion{index}" for index in range(MAX_APPENDED_EXPANSIONS)
    )


def test_expansion_never_exceeds_query_character_limit() -> None:
    long_query = "vpn " + "x" * (MAX_QUERY_CHARACTERS - 10)
    result = expand_query(long_query.strip(), [("vpn", "virtual private network")])
    assert result.applied is False
    assert len(result.search_query) <= MAX_QUERY_CHARACTERS
    assert len(result.lexical_query) <= MAX_QUERY_CHARACTERS


@pytest.mark.anyio
async def test_disabled_switch_returns_identity_without_database() -> None:
    def factory(_: RequestContext) -> object:
        raise AssertionError("disabled expansion must not open a unit of work")

    service = RetrievalService(
        factory,  # type: ignore[arg-type]
        AuthorizationService(),
        make_test_settings(),
    )
    result = await service._expanded_query(_context(), "vpn not working")
    assert result.applied is False
    assert result.search_query == "vpn not working"


@pytest.mark.anyio
async def test_unlisted_tenant_returns_identity_without_database() -> None:
    def factory(_: RequestContext) -> object:
        raise AssertionError("unlisted tenant must not open a unit of work")

    settings = make_test_settings(
        retrieval_synonym_expansion_enabled=True,
        retrieval_synonym_expansion_tenant_ids="99999999-0000-0000-0000-000000000001",
    )
    service = RetrievalService(
        factory,  # type: ignore[arg-type]
        AuthorizationService(),
        settings,
    )
    result = await service._expanded_query(_context(), "vpn not working")
    assert result.applied is False


@pytest.mark.anyio
async def test_expansion_failure_falls_back_to_unexpanded_query() -> None:
    def broken_factory(_: RequestContext) -> object:
        raise RuntimeError("registry unavailable")

    settings = make_test_settings(
        retrieval_synonym_expansion_enabled=True,
        retrieval_synonym_expansion_tenant_ids=str(TENANT),
    )
    service = RetrievalService(
        broken_factory,  # type: ignore[arg-type]
        AuthorizationService(),
        settings,
    )
    result = await service._expanded_query(_context(), "vpn not working")
    assert result.applied is False
    assert result.search_query == "vpn not working"


def _context() -> RequestContext:
    return RequestContext(
        TENANT,
        USER,
        "retrieval-expansion",
        frozenset({"EMPLOYEE"}),
        frozenset(),
        None,
        str(TENANT),
        "retrieval-expansion",
    )
