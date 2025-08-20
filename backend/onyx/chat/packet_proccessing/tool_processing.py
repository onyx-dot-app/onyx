from collections.abc import Generator

from onyx.context.search.utils import chunks_or_sections_to_search_docs
from onyx.context.search.utils import dedupe_documents
from onyx.db.chat import create_db_search_doc
from onyx.db.chat import create_search_doc_from_user_file
from onyx.db.chat import translate_db_search_doc_to_server_search_doc
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import SearchDoc as DbSearchDoc
from onyx.db.models import UserFile
from onyx.file_store.models import InMemoryChatFile
from onyx.file_store.utils import save_files
from onyx.server.query_and_chat.streaming_models import ImageGenerationToolDelta
from onyx.server.query_and_chat.streaming_models import Packet
from onyx.server.query_and_chat.streaming_models import SearchToolDelta
from onyx.server.query_and_chat.streaming_models import SectionEnd
from onyx.tools.tool_implementations.images.image_generation_tool import (
    ImageGenerationResponse,
)
from onyx.tools.tool_implementations.internet_search.models import (
    InternetSearchResponseSummary,
)
from onyx.tools.tool_implementations.internet_search.utils import (
    internet_search_response_to_search_docs,
)
from onyx.tools.tool_implementations.search.search_tool import SearchResponseSummary


def handle_search_tool_response_summary(
    current_ind: int,
    search_response: SearchResponseSummary,
    selected_search_docs: list[DbSearchDoc] | None,
    is_extended: bool,
    dedupe_docs: bool = False,
    user_files: list[UserFile] | None = None,
    loaded_user_files: list[InMemoryChatFile] | None = None,
) -> Generator[Packet, None, tuple[list[DbSearchDoc], list[int] | None]]:
    dropped_inds = None

    if not selected_search_docs:
        top_docs = chunks_or_sections_to_search_docs(search_response.top_sections)

        deduped_docs = top_docs
        if (
            dedupe_docs and not is_extended
        ):  # Extended tool responses are already deduped
            deduped_docs, dropped_inds = dedupe_documents(top_docs)

        with get_session_with_current_tenant() as db_session:
            reference_db_search_docs = [
                create_db_search_doc(server_search_doc=doc, db_session=db_session)
                for doc in deduped_docs
            ]

    else:
        reference_db_search_docs = selected_search_docs

    doc_ids = {doc.id for doc in reference_db_search_docs}
    if user_files is not None and loaded_user_files is not None:
        for user_file in user_files:
            if user_file.id in doc_ids:
                continue

            associated_chat_file = next(
                (
                    file
                    for file in loaded_user_files
                    if file.file_id == str(user_file.file_id)
                ),
                None,
            )
            # Use create_search_doc_from_user_file to properly add the document to the database
            if associated_chat_file is not None:
                with get_session_with_current_tenant() as db_session:
                    db_doc = create_search_doc_from_user_file(
                        user_file, associated_chat_file, db_session
                    )
                reference_db_search_docs.append(db_doc)

    response_docs = [
        translate_db_search_doc_to_server_search_doc(db_search_doc)
        for db_search_doc in reference_db_search_docs
    ]

    yield Packet(
        ind=current_ind,
        obj=SearchToolDelta(
            documents=response_docs,
        ),
    )

    yield Packet(
        ind=current_ind,
        obj=SectionEnd(),
    )

    return reference_db_search_docs, dropped_inds


def handle_internet_search_tool_response(
    current_ind: int,
    internet_search_response: InternetSearchResponseSummary,
) -> Generator[Packet, None, list[DbSearchDoc]]:
    server_search_docs = internet_search_response_to_search_docs(
        internet_search_response
    )

    with get_session_with_current_tenant() as db_session:
        reference_db_search_docs = [
            create_db_search_doc(server_search_doc=doc, db_session=db_session)
            for doc in server_search_docs
        ]
    response_docs = [
        translate_db_search_doc_to_server_search_doc(db_search_doc)
        for db_search_doc in reference_db_search_docs
    ]

    yield Packet(
        ind=current_ind,
        obj=SearchToolDelta(
            documents=response_docs,
        ),
    )

    yield Packet(
        ind=current_ind,
        obj=SectionEnd(),
    )

    return reference_db_search_docs


def handle_image_generation_tool_response(
    current_ind: int,
    img_generation_responses: list[ImageGenerationResponse],
) -> Generator[Packet, None, None]:

    # Save files and get file IDs
    file_ids = save_files(
        urls=[img.url for img in img_generation_responses if img.url],
        base64_files=[
            img.image_data for img in img_generation_responses if img.image_data
        ],
    )

    yield Packet(
        ind=current_ind,
        obj=ImageGenerationToolDelta(
            images=[
                {
                    "id": str(file_id),
                    "url": "",  # URL will be constructed by frontend
                    "prompt": img.revised_prompt,
                }
                for file_id, img in zip(file_ids, img_generation_responses)
            ]
        ),
    )

    # Emit ImageToolEnd packet with file information
    yield Packet(
        ind=current_ind,
        obj=SectionEnd(),
    )
