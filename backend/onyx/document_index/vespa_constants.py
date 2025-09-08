from onyx.configs.app_configs import VESPA_CLOUD_URL
from onyx.configs.app_configs import VESPA_CONFIG_SERVER_HOST
from onyx.configs.app_configs import VESPA_HOST
from onyx.configs.app_configs import VESPA_PORT
from onyx.configs.app_configs import VESPA_TENANT_PORT
from onyx.configs.constants import SOURCE_TYPE

# config server


VESPA_CONFIG_SERVER_URL = (
    VESPA_CLOUD_URL or f"http://{VESPA_CONFIG_SERVER_HOST}:{VESPA_TENANT_PORT}"
)
VESPA_APPLICATION_ENDPOINT = f"{VESPA_CONFIG_SERVER_URL}/application/v2"

# main search application
VESPA_APP_CONTAINER_URL = VESPA_CLOUD_URL or f"http://{VESPA_HOST}:{VESPA_PORT}"


# danswer_chunk below is defined in vespa/app_configs/schemas/danswer_chunk.sd.jinja
DOCUMENT_ID_ENDPOINT = (
    f"{VESPA_APP_CONTAINER_URL}/document/v1/default/{{index_name}}/docid"
)

# the default document id endpoint is http://localhost:8080/document/v1/default/danswer_chunk/docid

SEARCH_ENDPOINT = f"{VESPA_APP_CONTAINER_URL}/search/"

NUM_THREADS = (
    32  # since Vespa doesn't allow batching of inserts / updates, we use threads
)
MAX_ID_SEARCH_QUERY_SIZE = 400
# Suspect that adding too many "or" conditions will cause Vespa to timeout and return
# an empty list of hits (with no error status and coverage: 0 and degraded)
MAX_OR_CONDITIONS = 10
# up from 500ms for now, since we've seen quite a few timeouts
# in the long term, we are looking to improve the performance of Vespa
# so that we can bring this back to default
VESPA_TIMEOUT = "10s"
BATCH_SIZE = 128  # Specific to Vespa

TENANT_ID = "tenant_id"
DOCUMENT_ID = "document_id"
CHUNK_ID = "chunk_id"
BLURB = "blurb"
CONTENT = "content"
SOURCE_LINKS = "source_links"
SEMANTIC_IDENTIFIER = "semantic_identifier"
TITLE = "title"
SKIP_TITLE_EMBEDDING = "skip_title"
SECTION_CONTINUATION = "section_continuation"
EMBEDDINGS = "embeddings"
TITLE_EMBEDDING = "title_embedding"
ACCESS_CONTROL_LIST = "access_control_list"
DOCUMENT_SETS = "document_sets"
USER_FILE = "user_file"
USER_FOLDER = "user_folder"
USER_PROJECT = "user_project"
LARGE_CHUNK_REFERENCE_IDS = "large_chunk_reference_ids"
METADATA = "metadata"
METADATA_LIST = "metadata_list"
METADATA_SUFFIX = "metadata_suffix"
DOC_SUMMARY = "doc_summary"
CHUNK_CONTEXT = "chunk_context"
BOOST = "boost"
AGGREGATED_CHUNK_BOOST_FACTOR = "aggregated_chunk_boost_factor"
DOC_UPDATED_AT = "doc_updated_at"  # Indexed as seconds since epoch
PRIMARY_OWNERS = "primary_owners"
SECONDARY_OWNERS = "secondary_owners"
RECENCY_BIAS = "recency_bias"
HIDDEN = "hidden"
# for legacy reasons, called `name` in Vespa despite it really being an ID
IMAGE_FILE_NAME = "image_file_name"

# Specific to Vespa, needed for highlighting matching keywords / section
CONTENT_SUMMARY = "content_summary"


YQL_BASE = (
    f"select "
    f"documentid, "
    f"{DOCUMENT_ID}, "
    f"{CHUNK_ID}, "
    f"{BLURB}, "
    f"{CONTENT}, "
    f"{SOURCE_TYPE}, "
    f"{SOURCE_LINKS}, "
    f"{SEMANTIC_IDENTIFIER}, "
    f"{TITLE}, "
    f"{SECTION_CONTINUATION}, "
    f"{IMAGE_FILE_NAME}, "
    f"{BOOST}, "
    f"{AGGREGATED_CHUNK_BOOST_FACTOR}, "
    f"{HIDDEN}, "
    f"{DOC_UPDATED_AT}, "
    f"{PRIMARY_OWNERS}, "
    f"{SECONDARY_OWNERS}, "
    f"{LARGE_CHUNK_REFERENCE_IDS}, "
    f"{METADATA}, "
    f"{METADATA_SUFFIX}, "
    f"{DOC_SUMMARY}, "
    f"{CHUNK_CONTEXT}, "
    f"{CONTENT_SUMMARY} "
    f"from {{index_name}} where "
)
