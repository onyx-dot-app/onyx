from datetime import datetime
from typing import Any, Optional

import requests
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import LoadConnector, PollConnector, GenerateDocumentsOutput, SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError, Document, Section, TextSection


class BitrixConnector(LoadConnector, PollConnector):
    def __init__(
            self,
            bitrix_webhook_url: str,
            batch_size: int = INDEX_BATCH_SIZE,
    ) -> None:
        self.batch_size = batch_size
        self.bitrix_url = bitrix_webhook_url

    def _proccess_issues(self, start: Optional[datetime] = None,
                         end: Optional[datetime] = None) -> GenerateDocumentsOutput:
        link = self.bitrix_url
        if link is None:
            raise ConnectorMissingCredentialError("Bitrix")

        data = requests.get(link + "task.item.list.json").json()
        doc_batch: list[Document] = []

        for item in data["result"]:
            title = item["TITLE"]
            description = item["DESCRIPTION"].replace("\\r\\n", "\n")
            data_comments = requests.get(link + f"task.commentitem.getlist.json?TASKID={item['ID']}").json()
            comments = []

            for comment in data_comments["result"]:
                author = comment["AUTHOR_NAME"]
                message = comment["POST_MESSAGE"]
                comments.append(f'Author: {author}\nMessage: {message}')

            metadata_dict = {}
            if item["PRIORITY"]:
                metadata_dict['priority'] = item["PRIORITY"]
            if item["STATUS"]:
                metadata_dict['status'] = item["STATUS"]
            if item['ALLOW_TIME_TRACKING']:
                metadata_dict['tracker'] = item['ALLOW_TIME_TRACKING']

            description = title + '\n' + description + '\n' + '\n'.join(comments)

            doc_batch.append(
                Document(
                    id=link,
                    sections=[TextSection(link=link, text=description)],
                    source=DocumentSource.BITRIX,
                    semantic_identifier=title,
                    metadata=metadata_dict,
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_credentials(self, credentials: dict[str, Any]) -> Optional[dict[str, Any]]:
        # if "bitrix_webhook_url" in credentials:
        #     self.bitrix_url = credentials["bitrix_webhook_url"]
        # else:
        #     raise ValueError("Authorization data is not specified")
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._proccess_issues()

    def poll_source(
            self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._proccess_issues(start_datetime, end_datetime)


if __name__ == "__main__":
    import os

    connector = BitrixConnector()
    connector.load_credentials(
        {
            "bitrix_webhook_url": os.environ["BITRIX_WEBHOOK_URL"]
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))