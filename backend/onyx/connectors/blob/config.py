from typing import Annotated

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import BlobType
from onyx.connectors.connector_config import ConnectorConfig, CredentialBinding
from onyx.connectors.field_policy import FieldClass, FieldPolicy, ScopeOpaque

_IDENTITY = FieldPolicy(FieldClass.IDENTITY)


class BlobStorageCredentialBinding(CredentialBinding):
    # The connector annotates this as str and converts it with BlobType(...).
    # Document ids and the document source contain the bucket type.
    bucket_type: Annotated[BlobType, _IDENTITY]
    # Selects the R2 jurisdiction, which holds its own set of buckets.
    european_residency: Annotated[bool, _IDENTITY] = False
    # Selects the AWS partition, which holds its own set of bucket names.
    region_name: Annotated[str | None, _IDENTITY] = None


class BlobStorageConnectorConfig(BlobStorageCredentialBinding, ConnectorConfig):
    bucket_name: Annotated[str, _IDENTITY]
    # A key prefix, not a list: a longer prefix narrows and a shorter one widens.
    prefix: Annotated[str, FieldPolicy(FieldClass.SCOPE, scope=ScopeOpaque())] = ""
    batch_size: Annotated[int, FieldPolicy(FieldClass.COSMETIC)] = INDEX_BATCH_SIZE
