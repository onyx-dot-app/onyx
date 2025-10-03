import abc
from collections.abc import Generator
from collections.abc import Iterator
from types import TracebackType
from typing import Any
from typing import Generic
from typing import TypeAlias
from typing import TypeVar

from pydantic import BaseModel

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import ConnectorCheckpoint
from onyx.connectors.models import ConnectorFailure
from onyx.connectors.models import Document
from onyx.connectors.models import SlimDocument
from onyx.indexing.indexing_heartbeat import IndexingHeartbeatInterface
from onyx.utils.variable_functionality import fetch_ee_implementation_or_noop

SecondsSinceUnixEpoch = float

GenerateDocumentsOutput = Iterator[list[Document]]
GenerateSlimDocumentOutput = Iterator[list[SlimDocument]]

CT = TypeVar("CT", bound=ConnectorCheckpoint)


class BaseConnector(abc.ABC, Generic[CT]):
    REDIS_KEY_PREFIX = "da_connector_data:"
    # Common image file extensions supported across connectors
    IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".webp", ".gif"}

    @abc.abstractmethod
    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        raise NotImplementedError

    @staticmethod
    def parse_metadata(metadata: dict[str, Any]) -> list[str]:
        """Parse the metadata for a document/chunk into a string to pass to Generative AI as additional context"""
        custom_parser_req_msg = (
            "Specific metadata parsing required, connector has not implemented it."
        )
        metadata_lines = []
        for metadata_key, metadata_value in metadata.items():
            if isinstance(metadata_value, str):
                metadata_lines.append(f"{metadata_key}: {metadata_value}")
            elif isinstance(metadata_value, list):
                if not all([isinstance(val, str) for val in metadata_value]):
                    raise RuntimeError(custom_parser_req_msg)
                metadata_lines.append(f'{metadata_key}: {", ".join(metadata_value)}')
            else:
                raise RuntimeError(custom_parser_req_msg)
        return metadata_lines

    def validate_connector_settings(self) -> None:
        """
        Override this if your connector needs to validate credentials or settings.
        Raise an exception if invalid, otherwise do nothing.

        Default is a no-op (always successful).
        """

    def validate_perm_sync(self) -> None:
        """
        Don't override this; add a function to perm_sync_valid.py in the ee package
        to do permission sync validation
        """
        validate_connector_settings_fn = fetch_ee_implementation_or_noop(
            "onyx.connectors.perm_sync_valid",
            "validate_perm_sync",
            noop_return_value=None,
        )
        validate_connector_settings_fn(self)

    def set_allow_images(self, value: bool) -> None:
        """Implement if the underlying connector wants to skip/allow image downloading
        based on the application level image analysis setting."""

    def build_dummy_checkpoint(self) -> CT:
        # TODO: find a way to make this work without type: ignore
        return ConnectorCheckpoint(has_more=True)  # type: ignore


# Large set update or reindex, generally pulling a complete state or from a savestate file
class LoadConnector(BaseConnector):
    @abc.abstractmethod
    def load_from_state(self) -> GenerateDocumentsOutput:
        raise NotImplementedError


# Small set updates by time
class PollConnector(BaseConnector):
    @abc.abstractmethod
    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        raise NotImplementedError


# Slim connectors retrieve just the ids of documents
class SlimConnector(BaseConnector):
    @abc.abstractmethod
    def retrieve_all_slim_docs(
        self,
    ) -> GenerateSlimDocumentOutput:
        raise NotImplementedError


# Slim connectors retrieve both the ids AND
# permission syncing information for connected documents
class SlimConnectorWithPermSync(BaseConnector):
    @abc.abstractmethod
    def retrieve_all_slim_docs_perm_sync(
        self,
        start: SecondsSinceUnixEpoch | None = None,
        end: SecondsSinceUnixEpoch | None = None,
        callback: IndexingHeartbeatInterface | None = None,
    ) -> GenerateSlimDocumentOutput:
        raise NotImplementedError


class OAuthConnector(BaseConnector):
    class AdditionalOauthKwargs(BaseModel):
        # if overridden, all fields should be str type
        pass

    @classmethod
    @abc.abstractmethod
    def oauth_id(cls) -> DocumentSource:
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def oauth_authorization_url(
        cls,
        base_domain: str,
        state: str,
        additional_kwargs: dict[str, str],
    ) -> str:
        raise NotImplementedError

    @classmethod
    @abc.abstractmethod
    def oauth_code_to_token(
        cls,
        base_domain: str,
        code: str,
        additional_kwargs: dict[str, str],
    ) -> dict[str, Any]:
        raise NotImplementedError


T = TypeVar("T", bound="CredentialsProviderInterface")


class CredentialsProviderInterface(abc.ABC, Generic[T]):
    @abc.abstractmethod
    def __enter__(self) -> T:
        raise NotImplementedError

    @abc.abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def get_tenant_id(self) -> str | None:
        raise NotImplementedError

    @abc.abstractmethod
    def get_provider_key(self) -> str:
        """a unique key that the connector can use to lock around a credential
        that might be used simultaneously.

        Will typically be the credential id, but can also just be something random
        in cases when there is nothing to lock (aka static credentials)
        """
        raise NotImplementedError

    @abc.abstractmethod
    def get_credentials(self) -> dict[str, Any]:
        raise NotImplementedError

    @abc.abstractmethod
    def set_credentials(self, credential_json: dict[str, Any]) -> None:
        raise NotImplementedError

    @abc.abstractmethod
    def is_dynamic(self) -> bool:
        """If dynamic, the credentials may change during usage ... maening the client
        needs to use the locking features of the credentials provider to operate
        correctly.

        If static, the client can simply reference the credentials once and use them
        through the entire indexing run.
        """
        raise NotImplementedError


class CredentialsConnector(BaseConnector):
    """Implement this if the connector needs to be able to read and write credentials
    on the fly. Typically used with shared credentials/tokens that might be renewed
    at any time."""

    @abc.abstractmethod
    def set_credentials_provider(
        self, credentials_provider: CredentialsProviderInterface
    ) -> None:
        raise NotImplementedError


# Event driven
class EventConnector(BaseConnector):
    @abc.abstractmethod
    def handle_event(self, event: Any) -> GenerateDocumentsOutput:
        raise NotImplementedError


CheckpointOutput: TypeAlias = Generator[Document | ConnectorFailure, None, CT]


class CheckpointedConnector(BaseConnector[CT]):
    @abc.abstractmethod
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CT,
    ) -> CheckpointOutput[CT]:
        """Yields back documents or failures. Final return is the new checkpoint.

        Final return can be access via either:

        ```
        try:
            for document_or_failure in connector.load_from_checkpoint(start, end, checkpoint):
                print(document_or_failure)
        except StopIteration as e:
            checkpoint = e.value  # Extracting the return value
            print(checkpoint)
        ```

        OR

        ```
        checkpoint = yield from connector.load_from_checkpoint(start, end, checkpoint)
        ```
        """
        raise NotImplementedError

    @abc.abstractmethod
    def build_dummy_checkpoint(self) -> CT:
        raise NotImplementedError

    @abc.abstractmethod
    def validate_checkpoint_json(self, checkpoint_json: str) -> CT:
        """Validate the checkpoint json and return the checkpoint object"""
        raise NotImplementedError


class CheckpointedConnectorWithPermSync(CheckpointedConnector[CT]):
    @abc.abstractmethod
    def load_from_checkpoint_with_perm_sync(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: CT,
    ) -> CheckpointOutput[CT]:
        raise NotImplementedError
