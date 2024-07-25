import requests
from retry import retry

from danswer.configs.constants import DocumentSource
from danswer.connectors.models import InputType
from danswer.db.enums import IndexingStatus
from danswer.search.models import IndexFilters
from danswer.search.models import OptionalSearchSetting
from danswer.search.models import RetrievalDetails
from danswer.server.documents.models import ConnectorBase
from danswer.server.query_and_chat.models import ChatSessionCreationRequest
from ee.danswer.server.query_and_chat.models import BasicCreateChatMessageRequest
from tests.regression.answer_quality.cli_utils import get_api_server_host_port

GENERAL_HEADERS = {"Content-Type": "application/json"}


def _api_url_builder(run_suffix: str, api_path: str) -> str:
    return f"http://localhost:{get_api_server_host_port(run_suffix)}" + api_path


def _create_new_chat_session(run_suffix: str) -> int:
    create_chat_request = ChatSessionCreationRequest(
        persona_id=0,
        description=None,
    )
    body = create_chat_request.dict()

    create_chat_url = _api_url_builder(run_suffix, "/chat/create-chat-session/")

    response_json = requests.post(
        create_chat_url, headers=GENERAL_HEADERS, json=body
    ).json()
    chat_session_id = response_json.get("chat_session_id")

    if isinstance(chat_session_id, int):
        return chat_session_id
    else:
        raise RuntimeError(response_json)


@retry(tries=10, delay=10)
def get_answer_from_query(query: str, run_suffix: str) -> tuple[list[str], str]:
    filters = IndexFilters(
        source_type=None,
        document_set=None,
        time_cutoff=None,
        tags=None,
        access_control_list=None,
    )
    retrieval_options = RetrievalDetails(
        run_search=OptionalSearchSetting.ALWAYS,
        real_time=True,
        filters=filters,
        enable_auto_detect_filters=False,
    )

    chat_session_id = _create_new_chat_session(run_suffix)

    url = _api_url_builder(run_suffix, "/chat/send-message-simple-api/")

    new_message_request = BasicCreateChatMessageRequest(
        chat_session_id=chat_session_id,
        message=query,
        retrieval_options=retrieval_options,
        query_override=query,
    )

    body = new_message_request.dict()
    body["user"] = None
    try:
        response_json = requests.post(url, headers=GENERAL_HEADERS, json=body).json()
        simple_search_docs = response_json.get("simple_search_docs", [])
        answer = response_json.get("answer", "")
    except Exception as e:
        print("Failed to answer the questions:")
        print(f"\t {str(e)}")
        print("trying again")
        raise e

    return simple_search_docs, answer


@retry(tries=10, delay=10)
def check_if_query_ready(run_suffix: str) -> bool:
    url = _api_url_builder(run_suffix, "/manage/admin/connector/indexing-status/")
    try:
        indexing_status_dict = requests.get(url, headers=GENERAL_HEADERS).json()
    except Exception as e:
        print("Failed to check indexing status, API server is likely starting up:")
        print(f"\t {str(e)}")
        print("trying again")
        raise e

    ongoing_index_attempts = False
    doc_count = 0
    for index_attempt in indexing_status_dict:
        status = index_attempt["last_status"]
        if status == IndexingStatus.IN_PROGRESS or status == IndexingStatus.NOT_STARTED:
            ongoing_index_attempts = True
        doc_count += index_attempt["docs_indexed"]

    if not doc_count:
        print("No docs indexed, waiting for indexing to start")
    elif ongoing_index_attempts:
        print(
            f"{doc_count} docs indexed but waiting for ongoing indexing jobs to finish..."
        )

    return doc_count > 0 and not ongoing_index_attempts


def run_cc_once(run_suffix: str, connector_id: int, credential_id: int) -> None:
    url = _api_url_builder(run_suffix, "/manage/admin/connector/run-once/")
    body = {
        "connector_id": connector_id,
        "credential_ids": [credential_id],
        "from_beginning": True,
    }
    print("body:", body)
    response = requests.post(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        print("Connector created successfully:", response.json())
    else:
        print("Failed status_code:", response.status_code)
        print("Failed text:", response.text)


def create_cc_pair(run_suffix: str, connector_id: int, credential_id: int) -> None:
    url = _api_url_builder(
        run_suffix, f"/manage/connector/{connector_id}/credential/{credential_id}"
    )

    body = {"name": "zip_folder_contents", "is_public": True}
    print("body:", body)
    response = requests.put(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        print("Connector created successfully:", response.json())
    else:
        print("Failed status_code:", response.status_code)
        print("Failed text:", response.text)


def _get_existing_connector_names(run_suffix: str) -> list[str]:
    url = _api_url_builder(run_suffix, "/manage/connector")

    body = {
        "credential_json": {},
        "admin_public": True,
    }
    response = requests.get(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        connectors = response.json()
        return [connector["name"] for connector in connectors]
    else:
        raise RuntimeError(response.__dict__)


def create_connector(run_suffix: str, file_paths: list[str]) -> int:
    url = _api_url_builder(run_suffix, "/manage/admin/connector")
    connector_name = base_connector_name = "search_eval_connector"
    existing_connector_names = _get_existing_connector_names(run_suffix)

    count = 1
    while connector_name in existing_connector_names:
        connector_name = base_connector_name + "_" + str(count)
        count += 1

    connector = ConnectorBase(
        name=connector_name,
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={"file_locations": file_paths},
        refresh_freq=None,
        prune_freq=None,
        disabled=False,
    )

    body = connector.dict()
    print("body:", body)
    response = requests.post(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        print("Connector created successfully:", response.json())
        return response.json()["id"]
    else:
        raise RuntimeError(response.__dict__)


def create_credential(run_suffix: str) -> int:
    url = _api_url_builder(run_suffix, "/manage/credential")
    body = {
        "credential_json": {},
        "admin_public": True,
    }
    response = requests.post(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        print("credential created successfully:", response.json())
        return response.json()["id"]
    else:
        raise RuntimeError(response.__dict__)


@retry(tries=10, delay=2, backoff=2)
def upload_file(run_suffix: str, zip_file_path: str) -> list[str]:
    files = [
        ("files", open(zip_file_path, "rb")),
    ]

    api_path = _api_url_builder(run_suffix, "/manage/admin/connector/file/upload")
    try:
        response = requests.post(api_path, files=files)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        print("file uploaded successfully:", response.json())
        return response.json()["file_paths"]
    except Exception as e:
        print("File upload failed, waiting for API server to come up and trying again")
        raise e
