"""The registration seam's two rules.

A source that forgets to sign must not reach an open endpoint by omission,
and a source nobody imports must not silently fail to register.
"""

import sys
from collections.abc import Generator, Mapping

import pytest
from pydantic import ValidationError

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox import sources as sources_module
from onyx.connectors.event_inbox.source_registry import (
    _SPECS,
    WebhookRequest,
    WebhookSourceSpec,
    get_webhook_source,
    register_webhook_source,
    registered_webhook_sources,
    webhook_callback_url,
)
from onyx.connectors.event_models import EventParseResult

SOURCE = DocumentSource.MOCK_CONNECTOR


def _parser(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


def _verifier(request: WebhookRequest, secrets: Mapping[str, str]) -> None:  # noqa: ARG001
    return None


STUB_MODULE = "tests.unit.onyx.connectors.event_inbox.registering_source"


@pytest.fixture(autouse=True)
def clean_registry() -> Generator[None, None, None]:
    before = dict(_SPECS)
    try:
        yield
    finally:
        _SPECS.clear()
        _SPECS.update(before)
        # A source registers as a side effect of being imported, and an
        # import happens once per process. Dropping the module lets each
        # test exercise a first load rather than a cache hit.
        sys.modules.pop(STUB_MODULE, None)


def test_a_source_that_forgets_to_sign_is_refused() -> None:
    """The endpoint is unauthenticated and public, so an absent verifier
    cannot be a default anyone reaches by not thinking about it."""
    with pytest.raises(ValidationError, match="no verifier"):
        WebhookSourceSpec(source=SOURCE, slug="forgot", parser=_parser, verifier=None)


def test_unsigned_is_allowed_only_when_stated_outright() -> None:
    spec = WebhookSourceSpec(
        source=SOURCE,
        slug="unsigned",
        parser=_parser,
        verifier=None,
        allow_unsigned=True,
    )
    assert spec.verifier is None


def test_stating_both_is_refused_as_ambiguous() -> None:
    with pytest.raises(ValidationError, match="unambiguous"):
        WebhookSourceSpec(
            source=SOURCE,
            slug="both",
            parser=_parser,
            verifier=_verifier,
            allow_unsigned=True,
        )


def test_a_source_is_registered_only_once_its_module_is_imported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both the webhook server and the drain build from this registry, and
    neither imports a source by accident."""
    _SPECS.clear()
    monkeypatch.setattr(sources_module, "_loaded", False)
    monkeypatch.setattr(
        sources_module,
        "EVENT_SOURCE_MODULES",
        (STUB_MODULE,),
    )

    assert registered_webhook_sources() == []
    sources_module.load_event_sources()

    spec = get_webhook_source("registering-source")
    assert spec is not None
    assert spec.source == SOURCE


def test_a_source_that_fails_to_import_does_not_stop_the_others(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _SPECS.clear()
    monkeypatch.setattr(sources_module, "_loaded", False)
    monkeypatch.setattr(
        sources_module,
        "EVENT_SOURCE_MODULES",
        ("onyx.connectors.event_inbox.no_such_module", STUB_MODULE),
    )

    sources_module.load_event_sources()

    assert get_webhook_source("registering-source") is not None


def test_the_callback_url_is_what_an_admin_registers() -> None:
    assert webhook_callback_url("zoom").endswith("/webhook/zoom")


def test_a_second_source_cannot_take_a_registered_slug() -> None:
    """A slug is a live URL, so a clash must not quietly move an endpoint."""
    register_webhook_source(
        WebhookSourceSpec(
            source=SOURCE, slug="taken", parser=_parser, verifier=_verifier
        )
    )

    with pytest.raises(ValueError, match="already registered"):
        register_webhook_source(
            WebhookSourceSpec(
                source=DocumentSource.WEB,
                slug="taken",
                parser=_parser,
                verifier=_verifier,
            )
        )


def test_a_source_cannot_hold_two_slugs() -> None:
    """`webhook_source_for` returns one spec, so two would make the lookups
    disagree about where a source receives."""
    register_webhook_source(
        WebhookSourceSpec(
            source=SOURCE, slug="first", parser=_parser, verifier=_verifier
        )
    )

    with pytest.raises(ValueError, match="already receives events"):
        register_webhook_source(
            WebhookSourceSpec(
                source=SOURCE, slug="second", parser=_parser, verifier=_verifier
            )
        )


def test_a_source_that_registers_then_fails_leaves_nothing_behind(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Logging the failure is not enough: a half-registered spec would serve
    a route for a module whose import never finished."""
    _SPECS.clear()
    half = "tests.unit.onyx.connectors.event_inbox.half_registering_source"
    monkeypatch.setattr(sources_module, "_loaded", False)
    monkeypatch.setattr(sources_module, "EVENT_SOURCE_MODULES", (half, STUB_MODULE))
    try:
        sources_module.load_event_sources()

        assert get_webhook_source("half-registered") is None
        assert get_webhook_source("registering-source") is not None
    finally:
        sys.modules.pop(half, None)
