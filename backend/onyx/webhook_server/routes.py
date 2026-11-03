"""The routes every event source is served by. Order is the contract:
resolve the pair, verify, parse, store. Nothing is written before the
signature verifies.

The proxy strips `/webhook`, so routes are mounted at `/<slug>`.
"""

from collections.abc import Awaitable, Callable, Mapping

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from onyx.connectors.event_inbox.credentials import pair_secrets
from onyx.connectors.event_inbox.models import WebhookRequest, WebhookSourceSpec
from onyx.db.connector_event_inbox import get_active_event_cc_pairs, record_events
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.webhook_server.exceptions import WebhookAuthError, WebhookPayloadError

logger = setup_logger()

# Bounds what one unauthenticated caller can make the server read.
MAX_BODY_BYTES = 5 * 1024 * 1024


def build_webhook_router() -> APIRouter:
    """One route per registered endpoint, fixed when the app is built."""
    router = APIRouter()

    for spec in _registered():
        for endpoint in spec.endpoints:
            router.add_api_route(
                f"/{spec.slug}{endpoint}",
                _handler_for(spec, endpoint),
                methods=["POST"],
                name=f"webhook_{spec.slug}{endpoint}",
                include_in_schema=False,
            )
    return router


def _registered() -> list[WebhookSourceSpec]:
    from onyx.connectors.event_inbox.source_registry import registered_webhook_sources
    from onyx.connectors.event_inbox.sources import load_event_sources

    load_event_sources()
    return registered_webhook_sources()


async def _read_body(request: Request) -> bytes:
    """Read up to the limit, then stop, unlike `request.body()`."""
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > MAX_BODY_BYTES:
            raise OnyxError(OnyxErrorCode.BAD_REQUEST, "Webhook body too large")
        chunks.append(chunk)
    return b"".join(chunks)


def _handler_for(
    spec: WebhookSourceSpec,
    endpoint: str,
) -> Callable[[Request], Awaitable[Response]]:
    async def handle(request: Request) -> Response:
        raw_body = await _read_body(request)
        delivery = WebhookRequest(
            raw_body=raw_body,
            headers=dict(request.headers),
            endpoint=endpoint,
        )

        # Synchronous work off the loop: the server runs one worker.
        return await run_in_threadpool(_receive, spec, delivery)

    return handle


def _receive(spec: WebhookSourceSpec, delivery: WebhookRequest) -> Response:
    with get_session_with_current_tenant() as db_session:
        pairs = get_active_event_cc_pairs(db_session, spec.source)
        if not pairs:
            # 404, not 403: a source nobody set up should not look known.
            logger.info(
                "Dropped a %s delivery: no active event connector",
                spec.source.value,
            )
            raise OnyxError(OnyxErrorCode.NOT_FOUND)

        if spec.verifier is None and not spec.allow_unsigned:
            # The spec validator refuses this; do not trust that it ran.
            logger.error(
                "Refused a %s delivery: the source has no verifier",
                spec.source.value,
            )
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)

        pair, secrets = _attribute(spec, delivery, pairs)

        # Only after verification, or the responder is a signing oracle.
        if spec.challenge_responder:
            answered = _answer_challenge(spec, delivery, secrets)
            if answered is not None:
                return JSONResponse(answered)

        try:
            parsed = spec.parser(delivery)
        except WebhookPayloadError as e:
            logger.warning("Could not read a %s delivery: %s", spec.source.value, e)
            raise OnyxError(OnyxErrorCode.BAD_REQUEST, str(e))
        except Exception:
            # Still an unreadable body; 400 stops the provider retrying it.
            logger.exception("The %s parser raised", spec.source.value)
            raise OnyxError(OnyxErrorCode.BAD_REQUEST, "Unreadable payload")

        created = record_events(db_session, pair.id, spec.source, parsed.events)
        db_session.commit()

        # 200 for a redelivery too: the provider has nothing to fix.
        return JSONResponse(
            {
                "accepted": len(created),
                "duplicates": len(parsed.events) - len(created),
                "ignored": parsed.ignored,
            }
        )


def _attribute(
    spec: WebhookSourceSpec,
    delivery: WebhookRequest,
    pairs: list[ConnectorCredentialPair],
) -> tuple[ConnectorCredentialPair, Mapping[str, str]]:
    """The pair whose secret the delivery verifies against, so each account
    of a source can sign with its own. An unsigned source cannot tell its
    pairs apart, so it serves one."""
    if spec.verifier is None:
        if len(pairs) > 1:
            logger.error(
                "Refused a %s delivery: %s pairs receive an unsigned source",
                spec.source.value,
                len(pairs),
            )
            raise OnyxError(
                OnyxErrorCode.CONFLICT,
                "An unsigned source can serve only one connector.",
            )
        return pairs[0], pair_secrets(pairs[0])

    for pair in pairs:
        secrets = pair_secrets(pair)
        try:
            spec.verifier(delivery, secrets)
        except WebhookAuthError:
            continue
        except Exception:
            # Fail closed: a verifier that broke proved nothing.
            logger.exception(
                "The %s verifier raised for cc_pair %s",
                spec.source.value,
                pair.id,
            )
            continue
        return pair, secrets

    logger.warning(
        "Rejected a %s delivery: signature did not verify", spec.source.value
    )
    raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)


def _answer_challenge(
    spec: WebhookSourceSpec,
    delivery: WebhookRequest,
    secrets: Mapping[str, str],
) -> dict[str, object] | None:
    """Run the responder, answering 400 rather than 500 for a body it cannot
    read, so the provider does not retry it."""
    if spec.challenge_responder is None:
        return None
    try:
        return spec.challenge_responder(delivery, secrets)
    except WebhookPayloadError as e:
        logger.warning("Could not read a %s delivery: %s", spec.source.value, e)
        raise OnyxError(OnyxErrorCode.BAD_REQUEST, str(e))
    except Exception:
        logger.exception("The %s challenge responder raised", spec.source.value)
        raise OnyxError(OnyxErrorCode.BAD_REQUEST, "Unreadable payload")
