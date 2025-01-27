import os
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional

import lark_oapi as lark
from lark_oapi.api.wiki.v2 import ListSpaceRequest, ListSpaceNodeRequest,ListSpaceResponse,ListSpaceNodeResponse,Space,Node
from lark_oapi.api.docx.v1 import RawContentDocumentRequest, RawContentDocumentResponse,RawContentDocumentResponseBody,Document

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import (
    GenerateDocumentsOutput, LoadConnector, PollConnector, SlimConnector, SecondsSinceUnixEpoch
)
from onyx.connectors.models import ConnectorMissingCredentialError, Document, Section, SlimDocument
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _parse_timestamp(timestamp: Any, node_token: str) -> Optional[datetime]:
    try:
        if isinstance(timestamp, str):
            timestamp = int(timestamp)
        elif not isinstance(timestamp, (int, float)):
            raise ValueError(f"Unsupported timestamp type: {type(timestamp)}")

        return datetime.fromtimestamp(timestamp, tz=timezone.utc)  # 转换为 datetime 对象
    except (ValueError, TypeError):
        logger.error(f"Invalid timestamp for node {node_token}: {timestamp}")
        return None


class LarkWikiConnector(LoadConnector, PollConnector, SlimConnector):
    def __init__(self,
                 workspace_domain: str = "https://<your domain>.feishu.cn",
                 space_id: str = "",
                 root_page_id: str = "",
                 batch_size: int = 100) -> None:
        self.batch_size = batch_size
        self.client = None
        self.workspace_domain = workspace_domain
        self.space_id = space_id
        self.root_page_id = root_page_id
        if "feishu.cn" in self.workspace_domain:
            self.api_domain = "https://open.feishu.cn"
        else:
            self.api_domain = "https://open.larksuite.com"

    def load_credentials(self, credentials: Dict[str, Any]) -> None:
        lark_app_id = credentials.get("lark_app_id")
        lark_app_secret = credentials.get("lark_app_secret")

        if not lark_app_id or not lark_app_secret:
            raise ConnectorMissingCredentialError("Lark Wiki")

        self.client = lark.Client.builder() \
            .app_id(lark_app_id) \
            .app_secret(lark_app_secret) \
            .domain(self.api_domain) \
            .build()

    def _get_all_spaces(self) -> List[Space]:
        spaces = []
        page_token = None
        while True:
            request = ListSpaceRequest.builder() \
                .page_size(10) \
                .page_token(page_token if page_token else "") \
                .build()
            response:ListSpaceResponse = self.client.wiki.v2.space.list(request)
            if not response.success():
                logger.error(f"Failed to list spaces: {response.msg}")
                break
            spaces.extend(response.data.items)
            if not response.data.has_more:
                break
            page_token = response.data.page_token
        if self.space_id != "":
            spaces = [space for space in spaces if space.space_id == self.space_id]
        return spaces

    def _get_all_nodes(self, space_id: str, parent_node_token: [str] = "") -> List[Node]:
        nodes = []
        page_token = None
        while True:
            request = ListSpaceNodeRequest.builder() \
                .space_id(space_id) \
                .page_size(50) \
                .parent_node_token(parent_node_token) \
                .page_token(page_token if page_token else "") \
                .build()
            response:ListSpaceNodeResponse = self.client.wiki.v2.space_node.list(request)
            if not response.success():
                logger.error(f"Failed to list nodes for space {space_id}: {response.msg}")
                break
            nodes.extend(response.data.items)
            for node in response.data.items:
                if node.has_child:
                    child_nodes = self._get_all_nodes(space_id, node.node_token)
                    nodes.extend(child_nodes)
            if not response.data.has_more:
                break
            page_token = response.data.page_token
        return nodes

    def _get_document_content(self, document_id: str) ->  Optional[RawContentDocumentResponseBody]:
        request = RawContentDocumentRequest.builder() \
            .document_id(document_id) \
            .build()
        response:RawContentDocumentResponse = self.client.docx.v1.document.raw_content(request)
        if not response.success():
            logger.error(f"Failed to get document content for {document_id}: {response.msg}")
            return None
        return response.data

    def _yield_documents(
            self, start: Optional[datetime] = None, end: Optional[datetime] = None
    ) -> GenerateDocumentsOutput:
        spaces = self._get_all_spaces()
        batch: List[Document] = []
        for space in spaces:
            nodes = self._get_all_nodes(space.space_id, self.root_page_id)
            for node in nodes:
                if node.obj_type not in ["doc", "docx"]:
                    continue

                obj_edit_time = _parse_timestamp(node.obj_edit_time, node.obj_token)
                if obj_edit_time is None:
                    continue

                if start and end and not (start <= obj_edit_time <= end):
                    continue

                document:RawContentDocumentResponseBody= self._get_document_content(node.obj_token)
                if not document:
                    continue
                batch.append(
                    Document(
                        id=f"lark_wiki:{space.space_id}:{node.obj_token}",
                        sections=[
                            Section(
                                link=f"{self.workspace_domain}/wiki/{node.node_token}",
                                text=document.content
                            )
                        ],
                        source=DocumentSource.LARK_WIKI,
                        semantic_identifier=node.title,
                        doc_updated_at=obj_edit_time,
                        metadata={
                            "space": space.name,
                            "document_id": node.obj_token
                        }
                    )
                )
                if len(batch) == self.batch_size:
                    yield batch
                    batch = []
        if batch:
            yield batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        logger.debug("Loading all documents from Lark Wiki")
        return self._yield_documents()

    def poll_source(
            self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        logger.debug(f"Polling documents from Lark Wiki between {start} and {end}")
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        return self._yield_documents(start_datetime, end_datetime)

    def retrieve_all_slim_documents(
            self, start: Optional[SecondsSinceUnixEpoch] = None, end: Optional[SecondsSinceUnixEpoch] = None
    ) -> Generator[List[SlimDocument], None, None]:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc) if start else None
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc) if end else None
        spaces = self._get_all_spaces()
        batch: List[SlimDocument] = []
        for space in spaces:
            nodes = self._get_all_nodes(space.space_id, self.root_page_id)
            for node in nodes:
                if node.obj_type not in ["doc", "docx"]:
                    continue

                obj_edit_time = _parse_timestamp(node.obj_edit_time, node.obj_token)
                if obj_edit_time is None:
                    continue

                if start_datetime and end_datetime and not (start_datetime <= obj_edit_time <= end_datetime):
                    continue
                perm_sync_data = {
                    "space_id": space.space_id,
                    "owner_id": node.owner,
                    "node_token": node.node_token,
                    "permissions": {
                        "read": [],
                        "write": []
                    },
                    "last_sync_time": datetime.now(timezone.utc).isoformat()
                }
                batch.append(
                    SlimDocument(
                        id=f"lark_wiki:{space.space_id}:{node.obj_token}",
                        perm_sync_data= perm_sync_data
                    )
                )
                if len(batch) == self.batch_size:
                    yield batch
                    batch = []
        if batch:
            yield batch


if __name__ == "__main__":
    credentials_dict = {
        "lark_app_id": os.environ.get("LARK_APP_ID"),
        "lark_app_secret": os.environ.get("LARK_APP_SECRET"),
    }

    connector = LarkWikiConnector()
    connector.load_credentials(credentials_dict)

    try:
        document_batch_generator = connector.load_from_state()
        for document_batch in document_batch_generator:
            print("First batch of documents:")
            for doc in document_batch:
                print(f"Document ID: {doc.id}")
                print(f"Semantic Identifier: {doc.semantic_identifier}")
                print(f"Source: {doc.source}")
                print(f"Updated At: {doc.doc_updated_at}")
                print("Sections:")
                for section in doc.sections:
                    print(f"  - Link: {section.link}")
                    print(f"  - Text: {section.text[:5]}")
                print("---")
            break

    except ConnectorMissingCredentialError as e:
        print(f"Error: {e}")
    except Exception as e:
        print(f"An unexpected error occurred: {e}")