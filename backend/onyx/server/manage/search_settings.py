from fastapi import APIRouter
from fastapi import Depends
from fastapi import HTTPException
from fastapi import status
from sqlalchemy.orm import Session

from onyx.auth.users import current_admin_user
from onyx.auth.users import current_user
from onyx.configs.app_configs import DISABLE_INDEX_UPDATE_ON_SWAP
from onyx.context.search.models import SavedSearchSettings
from onyx.context.search.models import SearchSettingsCreationRequest
from onyx.db.connector_credential_pair import get_connector_credential_pairs
from onyx.db.connector_credential_pair import resync_cc_pair
from onyx.db.engine.sql_engine import get_session
from onyx.db.index_attempt import expire_index_attempts
from onyx.db.models import IndexModelStatus
from onyx.db.models import User
from onyx.db.search_settings import create_search_settings
from onyx.db.search_settings import delete_search_settings
from onyx.db.search_settings import get_current_search_settings
from onyx.db.search_settings import get_embedding_provider_from_provider_type
from onyx.db.search_settings import get_secondary_search_settings
from onyx.db.search_settings import update_current_search_settings
from onyx.db.search_settings import update_search_settings_status
from onyx.document_index.document_index_utils import get_multipass_config
from onyx.document_index.factory import get_default_document_index
from onyx.file_processing.unstructured import delete_unstructured_api_key
from onyx.file_processing.unstructured import get_unstructured_api_key
from onyx.file_processing.unstructured import update_unstructured_api_key
from onyx.natural_language_processing.search_nlp_models import clean_model_name
from onyx.server.manage.embedding.models import SearchSettingsDeleteRequest
from onyx.server.manage.models import FullModelVersionResponse
from onyx.server.models import IdReturn
from onyx.utils.logger import setup_logger
from shared_configs.configs import ALT_INDEX_SUFFIX
from shared_configs.configs import MULTI_TENANT

router = APIRouter(prefix="/search-settings")
logger = setup_logger()


@router.post("/set-new-search-settings")
def set_new_search_settings(
    search_settings_new: SearchSettingsCreationRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> IdReturn:
    """Creates a new EmbeddingModel row and cancels the previous secondary indexing if any
    Gives an error if the same model name is used as the current or secondary index
    """
    if search_settings_new.index_name:
        logger.warning("Index name was specified by request, this is not suggested")

    # Disallow contextual RAG for cloud deployments
    if MULTI_TENANT and search_settings_new.enable_contextual_rag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contextual RAG disabled in Onyx Cloud",
        )

    # Validate cloud provider exists or create new LiteLLM provider
    if search_settings_new.provider_type is not None:
        cloud_provider = get_embedding_provider_from_provider_type(
            db_session, provider_type=search_settings_new.provider_type
        )

        if cloud_provider is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"No embedding provider exists for cloud embedding type {search_settings_new.provider_type}",
            )

    search_settings = get_current_search_settings(db_session)

    if search_settings_new.index_name is None:
        # We define index name here
        index_name = f"danswer_chunk_{clean_model_name(search_settings_new.model_name)}"
        if (
            search_settings_new.model_name == search_settings.model_name
            and not search_settings.index_name.endswith(ALT_INDEX_SUFFIX)
        ):
            index_name += ALT_INDEX_SUFFIX
        search_values = search_settings_new.model_dump()
        search_values["index_name"] = index_name
        new_search_settings_request = SavedSearchSettings(**search_values)
    else:
        new_search_settings_request = SavedSearchSettings(
            **search_settings_new.model_dump()
        )

    secondary_search_settings = get_secondary_search_settings(db_session)

    if secondary_search_settings:
        # Cancel any background indexing jobs
        expire_index_attempts(
            search_settings_id=secondary_search_settings.id, db_session=db_session
        )

        # Mark previous model as a past model directly
        update_search_settings_status(
            search_settings=secondary_search_settings,
            new_status=IndexModelStatus.PAST,
            db_session=db_session,
        )

    new_search_settings = create_search_settings(
        search_settings=new_search_settings_request, db_session=db_session
    )

    # Ensure Vespa has the new index immediately
    get_multipass_config(search_settings)
    get_multipass_config(new_search_settings)
    document_index = get_default_document_index(search_settings, new_search_settings)

    document_index.ensure_indices_exist(
        primary_embedding_dim=search_settings.final_embedding_dim,
        primary_embedding_precision=search_settings.embedding_precision,
        secondary_index_embedding_dim=new_search_settings.final_embedding_dim,
        secondary_index_embedding_precision=new_search_settings.embedding_precision,
    )

    # Pause index attempts for the currently in use index to preserve resources
    if DISABLE_INDEX_UPDATE_ON_SWAP:
        expire_index_attempts(
            search_settings_id=search_settings.id, db_session=db_session
        )
        for cc_pair in get_connector_credential_pairs(db_session):
            resync_cc_pair(
                cc_pair=cc_pair,
                search_settings_id=new_search_settings.id,
                db_session=db_session,
            )

    db_session.commit()
    return IdReturn(id=new_search_settings.id)


@router.post("/cancel-new-embedding")
def cancel_new_embedding(
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    secondary_search_settings = get_secondary_search_settings(db_session)

    if secondary_search_settings:
        expire_index_attempts(
            search_settings_id=secondary_search_settings.id, db_session=db_session
        )

        update_search_settings_status(
            search_settings=secondary_search_settings,
            new_status=IndexModelStatus.PAST,
            db_session=db_session,
        )

        # remove the old index from the vector db
        primary_search_settings = get_current_search_settings(db_session)
        document_index = get_default_document_index(primary_search_settings, None)
        document_index.ensure_indices_exist(
            primary_embedding_dim=primary_search_settings.final_embedding_dim,
            primary_embedding_precision=primary_search_settings.embedding_precision,
            # just finished swap, no more secondary index
            secondary_index_embedding_dim=None,
            secondary_index_embedding_precision=None,
        )


@router.delete("/delete-search-settings")
def delete_search_settings_endpoint(
    deletion_request: SearchSettingsDeleteRequest,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    try:
        delete_search_settings(
            db_session=db_session,
            search_settings_id=deletion_request.search_settings_id,
        )
    except ValueError as e:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(e))


@router.get("/get-current-search-settings")
def get_current_search_settings_endpoint(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SavedSearchSettings:
    current_search_settings = get_current_search_settings(db_session)
    return SavedSearchSettings.from_db_model(current_search_settings)


@router.get("/get-secondary-search-settings")
def get_secondary_search_settings_endpoint(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> SavedSearchSettings | None:
    secondary_search_settings = get_secondary_search_settings(db_session)
    if not secondary_search_settings:
        return None

    return SavedSearchSettings.from_db_model(secondary_search_settings)


@router.get("/get-all-search-settings")
def get_all_search_settings(
    _: User | None = Depends(current_user),
    db_session: Session = Depends(get_session),
) -> FullModelVersionResponse:
    current_search_settings = get_current_search_settings(db_session)
    secondary_search_settings = get_secondary_search_settings(db_session)
    return FullModelVersionResponse(
        current_settings=SavedSearchSettings.from_db_model(current_search_settings),
        secondary_settings=(
            SavedSearchSettings.from_db_model(secondary_search_settings)
            if secondary_search_settings
            else None
        ),
    )


# Updates current non-reindex search settings
@router.post("/update-inference-settings")
def update_saved_search_settings(
    search_settings: SavedSearchSettings,
    _: User | None = Depends(current_admin_user),
    db_session: Session = Depends(get_session),
) -> None:
    # Disallow contextual RAG for cloud deployments
    if MULTI_TENANT and search_settings.enable_contextual_rag:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Contextual RAG disabled in Onyx Cloud",
        )

    update_current_search_settings(
        search_settings=search_settings, db_session=db_session
    )


@router.get("/unstructured-api-key-set")
def unstructured_api_key_set(
    _: User | None = Depends(current_admin_user),
) -> bool:
    api_key = get_unstructured_api_key()
    print(api_key)
    return api_key is not None


@router.put("/upsert-unstructured-api-key")
def upsert_unstructured_api_key(
    unstructured_api_key: str,
    _: User | None = Depends(current_admin_user),
) -> None:
    update_unstructured_api_key(unstructured_api_key)


@router.delete("/delete-unstructured-api-key")
def delete_unstructured_api_key_endpoint(
    _: User | None = Depends(current_admin_user),
) -> None:
    delete_unstructured_api_key()
