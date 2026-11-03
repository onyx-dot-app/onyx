"""The extension point an out-of-repo source depends on.

A source can be installed beside Onyx rather than shipped in it, so these
fix the two things such a package relies on: that one call claims
everything a source needs, and that configuration can name its module.
"""

import os
import subprocess
import sys
from collections.abc import Generator, Mapping, Sequence

import pytest

from onyx.configs.constants import DocumentSource
from onyx.connectors.event_inbox.models import (
    EventHandler,
    WebhookRequest,
    WebhookSourceSpec,
)
from onyx.connectors.event_inbox.registration import (
    claimed_event_sources,
    get_event_source,
    register_event_source,
    unregister_event_source,
)
from onyx.connectors.event_inbox.source_registry import get_webhook_source
from onyx.connectors.event_models import EventParseResult
from onyx.connectors.models import Document
from onyx.context.search.enrichment.registry import (
    enrichment_source_types,
    get_enrichment_filter,
)
from onyx.context.search.models import InferenceChunk
from onyx.db.models import ConnectorEventInbox

SOURCE = DocumentSource.MOCK_CONNECTOR
SLUG = "registration-test"
_STUB_MODULE = "tests.unit.onyx.connectors.event_inbox.registering_source"


def _parse(request: WebhookRequest) -> EventParseResult:  # noqa: ARG001
    return EventParseResult()


def _handler(
    event: ConnectorEventInbox,  # noqa: ARG001
    secrets: Mapping[str, str],  # noqa: ARG001
) -> Document | None:
    return None


def _permit(
    user_email: str,  # noqa: ARG001
    chunks: Sequence[InferenceChunk],
    secrets: Mapping[str, str],  # noqa: ARG001
) -> list[InferenceChunk]:
    return list(chunks)


def _handler_of(source: DocumentSource) -> EventHandler | None:
    record = get_event_source(source)
    return record.handler if record is not None else None


def _spec() -> WebhookSourceSpec:
    return WebhookSourceSpec(
        source=SOURCE,
        slug=SLUG,
        parser=_parse,
        verifier=None,
        allow_unsigned=True,
    )


@pytest.fixture(autouse=True)
def restore() -> Generator[None, None, None]:
    """Hand the source back to whoever held it."""
    displaced = get_event_source(SOURCE)
    unregister_event_source(SOURCE)
    try:
        yield
    finally:
        unregister_event_source(SOURCE)
        if displaced is not None:
            register_event_source(
                webhook=displaced.webhook,
                handler=displaced.handler,
                permission_filter=displaced.permission_filter,
            )


def test_one_call_claims_the_route_and_the_drain() -> None:
    register_event_source(webhook=_spec(), handler=_handler)

    assert get_webhook_source(SLUG) is not None
    assert _handler_of(SOURCE) is _handler
    assert SOURCE in claimed_event_sources()


def test_a_source_is_searchable_unless_it_asks_not_to_be() -> None:
    """The permission filter is what withholds a source. Most sources index
    like any other connector."""
    register_event_source(webhook=_spec(), handler=_handler)

    assert SOURCE not in enrichment_source_types()


def test_a_permission_filter_withholds_the_source() -> None:
    register_event_source(webhook=_spec(), handler=_handler, permission_filter=_permit)

    assert SOURCE in enrichment_source_types()
    assert get_enrichment_filter(SOURCE) is _permit


def test_unregistering_gives_up_everything_at_once() -> None:
    """The loader rolls a failed import back with this."""
    register_event_source(webhook=_spec(), handler=_handler, permission_filter=_permit)

    unregister_event_source(SOURCE)

    assert get_webhook_source(SLUG) is None
    assert _handler_of(SOURCE) is None
    assert get_enrichment_filter(SOURCE) is None
    assert SOURCE not in claimed_event_sources()


def test_configuration_names_modules_for_the_loader() -> None:
    """The private-package path: `EXTRA_EVENT_SOURCE_MODULES` reaches the
    loader's list. A fresh interpreter, since the list is read at import."""
    env = {**os.environ, "EXTRA_EVENT_SOURCE_MODULES": " acme.events , other.events,"}
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            "from onyx.connectors.event_inbox.sources import EVENT_SOURCE_MODULES;"
            "print(','.join(EVENT_SOURCE_MODULES))",
        ],
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )

    loaded = result.stdout.strip().split(",")
    assert loaded[-2:] == ["acme.events", "other.events"]


def test_a_configured_module_registers_through_the_loader(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from onyx.connectors.event_inbox import sources as sources_module

    monkeypatch.setattr(sources_module, "EVENT_SOURCE_MODULES", (_STUB_MODULE,))
    sources_module.reset_event_sources()
    try:
        sources_module.load_event_sources()

        assert get_webhook_source("registering-source") is not None
    finally:
        sys.modules.pop(_STUB_MODULE, None)
        sources_module.reset_event_sources()


def test_a_second_module_claiming_a_source_leaves_the_first_alone() -> None:
    """A refused module must not have replaced the incumbent's handler: the
    loader could not put it back."""

    def _other_handler(
        event: ConnectorEventInbox,  # noqa: ARG001
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> Document | None:
        return None

    register_event_source(webhook=_spec(), handler=_handler)

    with pytest.raises(ValueError):
        register_event_source(
            webhook=WebhookSourceSpec(
                source=SOURCE,
                slug="a-second-slug",
                parser=_parse,
                verifier=None,
                allow_unsigned=True,
            ),
            handler=_other_handler,
        )

    assert _handler_of(SOURCE) is _handler
    assert get_webhook_source(SLUG) is not None
    assert get_webhook_source("a-second-slug") is None


def test_a_second_module_claiming_a_slug_leaves_the_first_alone() -> None:
    def _other_handler(
        event: ConnectorEventInbox,  # noqa: ARG001
        secrets: Mapping[str, str],  # noqa: ARG001
    ) -> Document | None:
        return None

    register_event_source(webhook=_spec(), handler=_handler)

    with pytest.raises(ValueError):
        register_event_source(
            webhook=WebhookSourceSpec(
                source=DocumentSource.WEB,
                slug=SLUG,
                parser=_parse,
                verifier=None,
                allow_unsigned=True,
            ),
            handler=_other_handler,
        )

    assert _handler_of(SOURCE) is _handler
    assert _handler_of(DocumentSource.WEB) is None
