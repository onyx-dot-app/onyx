import requests
from retry import retry

from ee.onyx.server.query_and_chat.models import OneShotQARequest
from onyx.chat.models import ThreadMessage
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import MessageType
from onyx.connectors.models import InputType
from onyx.context.search.enums import OptionalSearchSetting
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import RetrievalDetails
from onyx.db.enums import IndexingStatus
from onyx.server.documents.models import ConnectorBase
from tests.regression.answer_quality.cli_utils import get_api_server_host_port

GENERAL_HEADERS = {"Content-Type": "application/json"}


def _api_url_builder(env_name: str, api_path: str) -> str:
    if env_name:
        return f"http://localhost:{get_api_server_host_port(env_name)}" + api_path
    else:
        return "http://localhost:8080" + api_path


@retry(tries=5, delay=5)
def get_answer_from_query(
    query: str, only_retrieve_docs: bool, env_name: str
) -> tuple[list[str], str]:
    filters = IndexFilters(
        source_type=None,
        document_set=None,
        time_cutoff=None,
        tags=None,
        access_control_list=None,
    )

    messages = [ThreadMessage(message=query, sender=None, role=MessageType.USER)]

    new_message_request = OneShotQARequest(
        messages=messages,
        persona_id=0,
        retrieval_options=RetrievalDetails(
            run_search=OptionalSearchSetting.ALWAYS,
            real_time=True,
            filters=filters,
            enable_auto_detect_filters=False,
        ),
        skip_gen_ai_answer_generation=only_retrieve_docs,
    )

    url = _api_url_builder(env_name, "/query/answer-with-citation/")
    headers = {
        "Content-Type": "application/json",
    }

    body = new_message_request.model_dump()
    body["user"] = None
    try:
        response_json = requests.post(url, headers=headers, json=body).json()
        context_data_list = response_json.get("contexts", {}).get("contexts", [])
        answer = response_json.get("answer", "") or ""
    except Exception as e:
        print("Failed to answer the questions:")
        print(f"\t {str(e)}")
        raise e

    return context_data_list, answer


@retry(tries=10, delay=10)
def check_indexing_status(env_name: str) -> tuple[int, bool]:
    url = _api_url_builder(env_name, "/manage/admin/connector/indexing-status/")
    try:
        indexing_status_dict = requests.post(
            url, headers=GENERAL_HEADERS, json={"get_all_connectors": True}
        ).json()
    except Exception as e:
        print("Failed to check indexing status, API server is likely starting up:")
        print(f"\t {str(e)}")
        print("trying again")
        raise e

    ongoing_index_attempts = False
    doc_count = 0
    for connectors_by_source in indexing_status_dict:
        connectors = connectors_by_source["indexing_statuses"]
        for connector in connectors:
            status = connector["last_status"]
            if (
                status == IndexingStatus.IN_PROGRESS
                or status == IndexingStatus.NOT_STARTED
            ):
                ongoing_index_attempts = True
            elif status == IndexingStatus.SUCCESS:
                doc_count += 16
            doc_count += connector["docs_indexed"]
            doc_count -= 16

    # all the +16 and -16 are to account for the fact that the indexing status
    # is only updated every 16 documents and will tells us how many are
    # chunked, not indexed. probably need to fix this. in the future!
    if doc_count:
        doc_count += 16
    return doc_count, ongoing_index_attempts


def run_cc_once(env_name: str, connector_id: int, credential_id: int) -> None:
    url = _api_url_builder(env_name, "/manage/admin/connector/run-once/")
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


def create_cc_pair(env_name: str, connector_id: int, credential_id: int) -> None:
    url = _api_url_builder(
        env_name, f"/manage/connector/{connector_id}/credential/{credential_id}"
    )

    body = {"name": "zip_folder_contents", "is_public": True, "groups": []}
    print("body:", body)
    response = requests.put(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        print("Connector created successfully:", response.json())
    else:
        print("Failed status_code:", response.status_code)
        print("Failed text:", response.text)


def _get_existing_connector_names(env_name: str) -> list[str]:
    url = _api_url_builder(env_name, "/manage/connector")

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


def create_connector(env_name: str, file_paths: list[str]) -> int:
    url = _api_url_builder(env_name, "/manage/admin/connector")
    connector_name = base_connector_name = "search_eval_connector"
    existing_connector_names = _get_existing_connector_names(env_name)

    count = 1
    while connector_name in existing_connector_names:
        connector_name = base_connector_name + "_" + str(count)
        count += 1

    connector = ConnectorBase(
        name=connector_name,
        source=DocumentSource.FILE,
        input_type=InputType.LOAD_STATE,
        connector_specific_config={
            "file_locations": file_paths,
            "file_names": [],  # For regression tests, no need for file_names
            "zip_metadata": {},
        },
        refresh_freq=None,
        prune_freq=None,
        indexing_start=None,
    )

    body = connector.model_dump()
    response = requests.post(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        return response.json()["id"]
    else:
        raise RuntimeError(response.__dict__)


def create_credential(env_name: str) -> int:
    url = _api_url_builder(env_name, "/manage/credential")
    body = {
        "credential_json": {},
        "admin_public": True,
        "source": DocumentSource.FILE,
    }
    response = requests.post(url, headers=GENERAL_HEADERS, json=body)
    if response.status_code == 200:
        print("credential created successfully:", response.json())
        return response.json()["id"]
    else:
        raise RuntimeError(response.__dict__)


@retry(tries=10, delay=2, backoff=2)
def upload_file(env_name: str, zip_file_path: str) -> list[str]:
    files = [
        ("files", open(zip_file_path, "rb")),
    ]

    api_path = _api_url_builder(env_name, "/manage/admin/connector/file/upload")
    try:
        response = requests.post(api_path, files=files)
        response.raise_for_status()  # Raises an HTTPError for bad responses
        print("file uploaded successfully:", response.json())
        return response.json()["file_paths"]
    except Exception as e:
        print("File upload failed, waiting for API server to come up and trying again")
        raise e
