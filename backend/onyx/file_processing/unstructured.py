from typing import IO, TYPE_CHECKING, Any

from sqlalchemy.orm import Session

from onyx.configs.constants import KV_UNSTRUCTURED_API_TOKEN_ID
from onyx.db.api_token import (
    UNSTRUCTURED_PLATFORM,
    get_api_token,
    get_unstructured_api_token_id,
    release_api_token,
    resolve_api_token,
)
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import ApiToken
from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.key_value_store.factory import get_kv_store
from onyx.key_value_store.interface import KvKeyNotFoundError
from onyx.server.manage.api_token.models import ApiTokenInput
from onyx.utils.logger import setup_logger

if TYPE_CHECKING:
    from unstructured_client.models import operations


logger = setup_logger()


def get_unstructured_api_token(db_session: Session) -> ApiToken | None:
    token_id = get_unstructured_api_token_id()
    return get_api_token(db_session, token_id) if token_id is not None else None


def get_unstructured_api_key() -> str | None:
    if get_unstructured_api_token_id() is None:
        return None
    with get_session_with_current_tenant() as db_session:
        token = get_unstructured_api_token(db_session)
        return token.value.get_value(apply_mask=False) if token else None


def update_unstructured_api_key(
    db_session: Session, api_key: ApiTokenInput
) -> ApiToken:
    """Point Unstructured at the token the input names and commit. The old
    token is released after the KV entry moves, so it no longer counts as used."""
    previous_id = get_unstructured_api_token_id()
    token = resolve_api_token(
        db_session,
        api_key,
        platform=UNSTRUCTURED_PLATFORM,
        base_url=None,
        current_token_id=previous_id,
    )
    if token is None:
        raise OnyxError(OnyxErrorCode.INVALID_INPUT, "API key cannot be empty")
    db_session.commit()
    get_kv_store().store(KV_UNSTRUCTURED_API_TOKEN_ID, token.id)
    if previous_id is not None and previous_id != token.id:
        release_api_token(db_session, previous_id)
        db_session.commit()
    return token


def delete_unstructured_api_key(db_session: Session) -> None:
    """Remove the KV entry, then release the token it pointed to, and commit."""
    token_id = get_unstructured_api_token_id()
    try:
        get_kv_store().delete(KV_UNSTRUCTURED_API_TOKEN_ID)
    except KvKeyNotFoundError:
        return
    if token_id is not None:
        release_api_token(db_session, token_id)
        db_session.commit()


def _sdk_partition_request(
    file: IO[Any], file_name: str, **kwargs: Any
) -> "operations.PartitionRequest":
    from unstructured_client.models import operations, shared

    file.seek(0, 0)
    try:
        request = operations.PartitionRequest(
            partition_parameters=shared.PartitionParameters(
                files=shared.Files(content=file.read(), file_name=file_name),
                **kwargs,
            ),
        )
        return request
    except Exception as e:
        logger.error(
            "Error creating partition request for file %s: %s", file_name, str(e)
        )
        raise


def unstructured_to_text(file: IO[Any], file_name: str) -> str:
    from unstructured_client import UnstructuredClient

    logger.debug("Starting to read file: %s", file_name)
    req = _sdk_partition_request(file, file_name, strategy="fast")

    unstructured_client = UnstructuredClient(api_key_auth=get_unstructured_api_key())

    response = unstructured_client.general.partition(request=req)

    if response.status_code != 200:
        err = f"Received unexpected status code {response.status_code} from Unstructured API."
        logger.error(err)
        raise ValueError(err)

    # The API returns one dict per document element; only its text is needed.
    return "\n\n".join(el.get("text", "") for el in response.elements or [])
