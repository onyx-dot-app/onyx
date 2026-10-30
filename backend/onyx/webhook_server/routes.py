"""The one route every event-based source is served by.

A source supplies a `WebhookSourceSpec`; this builds the endpoint. The order
below is the contract: resolve the pair, prove the delivery is genuine, parse
it, store it. Nothing is written before the signature is checked, so an
unauthenticated caller cannot fill the table.
"""

from collections.abc import Awaitable, Callable

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, Response
from starlette.concurrency import run_in_threadpool

from onyx.connectors.event_inbox.source_registry import (
    WebhookRequest,
    WebhookSourceSpec,
)
from onyx.db.connector_event_inbox import get_active_event_cc_pairs, record_events
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ConnectorCredentialPair
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.utils.logger import setup_logger
from onyx.webhook_server.exceptions import WebhookAuthError, WebhookPayloadError

logger = setup_logger()

# A provider that batches is still one HTTP request; this bounds what one
# unauthenticated caller can make the server parse.
MAX_BODY_BYTES = 5 * 1024 * 1024


def _pair_secrets(pair: ConnectorCredentialPair) -> dict[str, str]:
    credential_json = pair.credential.credential_json
    if credential_json is None:
        return {}
    values = credential_json.get_value(apply_mask=False)
    return {key: value for key, value in values.items() if isinstance(value, str)}


def build_webhook_router() -> APIRouter:
    """One route per registered source, fixed when the app is built.

    The route always exists; whether it accepts a delivery depends on there
    being an active EVENT pair, which is what connector setup creates.
    """
    router = APIRouter()

    for spec in _registered():
        router.add_api_route(
            f"/{spec.slug}",
            _handler_for(spec),
            methods=["POST"],
            name=f"webhook_{spec.slug}",
            # The provider reads the status code, not a schema.
            include_in_schema=False,
        )
    return router


def _registered() -> list[WebhookSourceSpec]:
    from onyx.connectors.event_inbox.source_registry import registered_webhook_sources
    from onyx.connectors.event_inbox.sources import load_event_sources

    load_event_sources()
    return registered_webhook_sources()


async def _read_body(request: Request) -> bytes:
    """Read up to the limit, then stop.

    `request.body()` buffers the whole payload before any check runs, so an
    unauthenticated caller could spend the server's memory first. The proxy
    in front allows far more than this.
    """
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
) -> Callable[[Request], Awaitable[Response]]:
    async def handle(request: Request) -> Response:
        raw_body = await _read_body(request)
        delivery = WebhookRequest(raw_body=raw_body, headers=dict(request.headers))

        # The database work and the source's own callbacks are synchronous,
        # and this server runs one worker: inline they would stall every
        # other delivery and the health probe.
        return await run_in_threadpool(_receive, spec, delivery)

    return handle


def _receive(spec: WebhookSourceSpec, delivery: WebhookRequest) -> Response:
    with get_session_with_current_tenant() as db_session:
        pairs = get_active_event_cc_pairs(db_session, spec.source)
        if not pairs:
            # The source is registered but nobody has set the connector
            # up, so there is no ACL to attribute a document to. 404
            # rather than 403: an endpoint nobody enabled should not
            # confirm that Onyx knows this source.
            logger.info(
                "Dropped a %s delivery: no active event connector",
                spec.source.value,
            )
            raise OnyxError(OnyxErrorCode.NOT_FOUND)

        # One pair per source for now. A source that serves several
        # accounts resolves between them from the payload, which needs a
        # routing key the spec does not yet declare.
        pair = pairs[0]
        secrets = _pair_secrets(pair)

        if spec.verifier is None and not spec.allow_unsigned:
            # The spec validator already refuses this combination, so
            # reaching here means a spec was built around it. Refuse the
            # write rather than trust that the earlier check ran.
            logger.error(
                "Refused a %s delivery: the source has no verifier",
                spec.source.value,
            )
            raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)

        if spec.verifier is not None:
            try:
                spec.verifier(delivery, secrets)
            except WebhookAuthError:
                logger.warning(
                    "Rejected a %s delivery: signature did not verify",
                    spec.source.value,
                )
                raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)
            except Exception:
                # A verifier that broke proved nothing, so refuse. Fail
                # closed: a malformed header must not become a way in.
                logger.exception(
                    "The %s verifier raised; refusing the delivery",
                    spec.source.value,
                )
                raise OnyxError(OnyxErrorCode.UNAUTHENTICATED)

        # After verification, never before: the responder answers with
        # the secret applied to caller-chosen input.
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
            # A parser reaching into a body it did not expect raises
            # KeyError, TypeError and the rest. That is still a body this
            # source cannot read, and 400 stops the provider retrying it
            # for days.
            logger.exception("The %s parser raised", spec.source.value)
            raise OnyxError(OnyxErrorCode.BAD_REQUEST, "Unreadable payload")

        created = record_events(db_session, pair.id, spec.source, parsed.events)
        db_session.commit()

        # 200 for a redelivery too: the provider has nothing to fix, and
        # retrying would only write the same conflict again.
        return JSONResponse(
            {
                "accepted": len(created),
                "duplicates": len(parsed.events) - len(created),
                "ignored": parsed.ignored,
            }
        )


def _answer_challenge(
    spec: WebhookSourceSpec,
    delivery: WebhookRequest,
    secrets: dict[str, str],
) -> dict[str, object] | None:
    """Run the handshake responder without letting it 500 the route.

    A responder reads the body to decide whether this is a handshake, so an
    unreadable body reaches it first. A 500 here would make the provider
    retry a body that will never parse.
    """
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
