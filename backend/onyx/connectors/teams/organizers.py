"""Meeting organizers: Graph lists what a scheduled meeting leaves behind (its
transcript, its chat) per user, so those content types are walked organizer by
organizer, after the channels and several organizers at a time."""

import abc
from collections.abc import Callable, Generator, Iterator
from typing import Any
from urllib.parse import quote

import requests
from office365.graph_client import GraphClient
from pydantic import BaseModel

from onyx.connectors.exceptions import (
    ConnectorValidationError,
    InsufficientPermissionsError,
    UnexpectedValidationError,
)
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import (
    BasicExpertInfo,
    ConnectorFailure,
    Document,
    SlimDocument,
)
from onyx.connectors.teams.refusals import graph_said, status
from onyx.connectors.teams.session import TeamsSession
from onyx.connectors.teams.sources import SLIM_WALK, SlimWalk
from onyx.connectors.teams.utils import (
    GraphRetriesExhausted,
    escape_odata_string,
    get_json_with_retry,
    iter_values,
    next_page_url,
)
from onyx.utils.batching import batch_generator
from onyx.utils.logger import setup_logger
from onyx.utils.threadpool_concurrency import parallel_yield

logger = setup_logger()

# Graph lists per organizer and a listing costs the same with or without
# content, so a tenant is walked several organizers at a time. Eight measured 7
# times faster with no throttling, sixteen only 9 with slower calls.
ORGANIZER_WORKERS = 8

# A page of organizers rides in the indexing checkpoint, so pages stay small.
USER_PAGE_SIZE = 100
# Only a user with a Teams plan can organize a meeting, and a tenant can hold
# thousands of accounts without one. Graph filters on assigned plans only as an
# advanced query, which is a count and this header on every page.
ADVANCED_QUERY = {"ConsistencyLevel": "eventual"}
ORGANIZERS_URL = (
    "users?$select=id,userPrincipalName,mail,displayName"
    "&$filter=accountEnabled eq true and assignedPlans/any("
    "p:p/service eq 'TeamspaceAPI' and p/capabilityStatus eq 'Enabled')"
    f"&$count=true&$top={USER_PAGE_SIZE}"
)


class Organizer(BaseModel):
    """A user whose scheduled meetings are exported."""

    id: str
    email: str | None
    display_name: str | None

    @classmethod
    def from_graph(cls, row: dict[str, Any]) -> "Organizer":
        return cls(
            id=row["id"],
            email=(row.get("mail") or row.get("userPrincipalName") or None),
            display_name=row.get("displayName"),
        )


def iter_organizers(
    graph_client: GraphClient,
    principal_names: list[str],
    before_page: Callable[[], None] | None = None,
) -> Generator[Organizer]:
    """The configured users, or every enabled user with a Teams plan when none
    are configured. A configured name that resolves to nothing raises.
    ``before_page`` runs ahead of each user page request."""
    if principal_names:
        yield from _resolve_organizers(graph_client, principal_names)
        return
    for row in iter_values(graph_client, ORGANIZERS_URL, before_page, ADVANCED_QUERY):
        yield Organizer.from_graph(row)


def fetch_organizer_page(
    graph_client: GraphClient, principal_names: list[str], page_url: str | None
) -> tuple[list[Organizer], str | None]:
    """One page of enabled users with a Teams plan from ``page_url`` (the first
    page when None) and the link to the next. Configured names are one page of
    their own."""
    if principal_names:
        return _resolve_organizers(graph_client, principal_names), None
    page_url = page_url or ORGANIZERS_URL
    json_response = get_json_with_retry(graph_client, page_url, ADVANCED_QUERY)
    organizers = [
        Organizer.from_graph(row)
        for row in json_response.get("value", [])
        if isinstance(row, dict)
    ]
    return organizers, next_page_url(graph_client, json_response, page_url)


def _resolve_organizers(
    graph_client: GraphClient, principal_names: list[str]
) -> list[Organizer]:
    # Eager on purpose: every configured name is resolved even when the caller
    # wants one, so a misspelled name fails at setup and not at index time. A
    # name goes into an OData string literal, so its apostrophes double.
    return [
        Organizer.from_graph(
            get_json_with_retry(
                graph_client,
                f"users('{quote(escape_odata_string(name), safe='@.')}')"
                "?$select=id,userPrincipalName,mail,displayName",
            )
        )
        for name in principal_names
    ]


def organizer_expert(organizer: Organizer) -> list[BasicExpertInfo]:
    if not organizer.email:
        return []
    return [BasicExpertInfo(display_name=organizer.display_name, email=organizer.email)]


class OrganizerSource(abc.ABC):
    """One content type Graph lists per meeting organizer."""

    # The form option that turns the source on, for setup messages.
    option: str

    @abc.abstractmethod
    def validate(self, organizer: Organizer) -> None:
        """Reads what indexing reads for one organizer and names what is
        missing: a grant, a tenant setting, a policy."""

    @abc.abstractmethod
    def index(
        self,
        organizer: Organizer,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Iterator[Document | ConnectorFailure]:
        """The organizer's documents that changed inside the window. A refusal
        that stays is recorded, anything else raises."""

    @abc.abstractmethod
    def slim(self, organizer: Organizer, walk: SlimWalk) -> Iterator[SlimDocument]:
        """Every document id the indexing walk writes for the organizer. An
        organizer the app may no longer read lists nothing, so their documents
        are pruned like any document the credential lost."""


class OrganizerStage:
    """Walks the organizers for every source that is on."""

    def __init__(
        self,
        session: TeamsSession,
        principal_names: list[str],
        sources: list[OrganizerSource],
    ) -> None:
        self._session = session
        self._principal_names = principal_names
        self._sources = sources
        # A saved page url Graph rejects recovers once per attempt, or a token
        # it always rejects would list the first page for ever.
        self._restarted_listing = False

    def validate(self) -> None:
        """One organizer is enough to probe with. Configured names are all
        resolved on the way, since resolving them is not lazy."""
        options = " and ".join(source.option for source in self._sources)
        try:
            organizer = next(
                iter_organizers(self._session.graph(), self._principal_names), None
            )
        except requests.HTTPError as e:
            if status(e) == 404 and self._principal_names:
                raise ConnectorValidationError(
                    "No user matches a configured organizer: Graph answered "
                    f"{status(e)}. {graph_said(e)}"
                )
            if status(e) in (401, 403):
                raise InsufficientPermissionsError(
                    f"{options} needs the User.Read.All application permission to "
                    f"list organizers ({status(e)})."
                )
            raise UnexpectedValidationError(f"Could not list organizers: {e}")
        except (GraphRetriesExhausted, requests.RequestException) as e:
            raise UnexpectedValidationError(f"Could not list organizers: {e}")
        if organizer is None:
            raise UnexpectedValidationError(
                f"No enabled user with a Teams license to check {options} on. "
                "Configure an organizer."
            )
        for source in self._sources:
            source.validate(organizer)

    def next_page(self, page_url: str | None) -> tuple[list[Organizer], str | None]:
        """The next page of organizers for the checkpoint, which is saved after
        every step and so never carries a whole tenant's directory."""
        graph_client = self._session.graph()
        try:
            organizers, next_url = fetch_organizer_page(
                graph_client, self._principal_names, page_url
            )
        except requests.HTTPError as e:
            # Graph answers a skip token it no longer honors with 400 or 410.
            if (
                page_url is None
                or self._restarted_listing
                or status(e) not in (400, 410)
            ):
                raise
            self._restarted_listing = True
            logger.warning(
                "The saved organizer page is no longer honored, listing the "
                "organizers from the start: %s",
                e,
            )
            organizers, next_url = fetch_organizer_page(
                graph_client, self._principal_names, None
            )
        logger.info("Listed %s meeting organizer(s)", len(organizers))
        return organizers, next_url

    def index_batch(
        self,
        todo: list[Organizer],
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Iterator[Document | ConnectorFailure]:
        """Takes one batch of organizers off ``todo`` and indexes them side by
        side. The Graph client is shared: a direct request builds its own
        options, so threads do not collide."""
        batch = todo[-ORGANIZER_WORKERS:]
        del todo[-ORGANIZER_WORKERS:]
        yield from parallel_yield(
            [self._index_one(organizer, start, end) for organizer in batch],
            max_workers=ORGANIZER_WORKERS,
        )

    def slim(self, walk: SlimWalk) -> Iterator[SlimDocument]:
        organizers = iter_organizers(
            self._session.graph(),
            self._principal_names,
            before_page=walk.raise_if_stopped,
        )
        for batch in batch_generator(organizers, ORGANIZER_WORKERS):
            # One stop check and one progress report per batch. Each source
            # honors a stop before every page of its own.
            walk.raise_if_stopped()
            if walk.callback:
                walk.callback.progress(SLIM_WALK, len(batch))
            yield from parallel_yield(
                [self._slim_one(organizer, walk) for organizer in batch],
                max_workers=ORGANIZER_WORKERS,
            )

    def _index_one(
        self,
        organizer: Organizer,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
    ) -> Iterator[Document | ConnectorFailure]:
        for source in self._sources:
            yield from source.index(organizer, start, end)

    def _slim_one(self, organizer: Organizer, walk: SlimWalk) -> Iterator[SlimDocument]:
        for source in self._sources:
            yield from source.slim(organizer, walk)
