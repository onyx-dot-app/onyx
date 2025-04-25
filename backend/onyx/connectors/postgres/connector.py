from datetime import datetime
from typing import Any

from onyx.connectors.interfaces import LoadConnector, PollConnector, GenerateDocumentsOutput, SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError, Document
from onyx.connectors.postgres.utils import PostgreSQLUtility


def clean_text(text: str) -> str:
    """Очистка текста для безопасного использования."""
    return "".join(c if c.isalnum() else "_" for c in text)


class PostgresConnector(LoadConnector, PollConnector):
    def __init__(self, content_columns: list[str],
                 metadata_columns: list[str], table_name: str | None = None, query: str | None = None,
                 batch_size: int = 10):
        self.imap_server = "imap.yandex.com"
        self.batch_size = batch_size
        self.connection: PostgreSQLUtility | None = None
        self.content_columns = content_columns
        self.metadata_columns = metadata_columns
        self.table_name = table_name
        self.query = query

    def load_credentials(self, credentials: dict[str, Any]) -> None:
        if "host" not in credentials or "password" not in credentials:
            raise ValueError("Password or email not provided in credentials")
        host = credentials['host']
        password = credentials['password']
        port = credentials['port'] if "port" in credentials else 5432
        database = credentials['database'] if "database" in credentials else "postgres"
        user = credentials['user'] if "user" in credentials else "postgres"

        self.connection = PostgreSQLUtility(host, port, database, user, password)
        try:
            self.connection.connect()
            print("success connect")
        except Exception as e:
            print(e)
            raise ConnectorMissingCredentialError("Invalid credentials for Postgres")

    def _process_postgres(self, start: datetime | None = None, end: datetime | None = None) -> GenerateDocumentsOutput:
        if not self.connection:
            raise ConnectorMissingCredentialError("Postgres")

        documents_from_postgres = self.connection.fetch_documents(
            self.table_name, self.query, self.content_columns, self.metadata_columns
        )

        doc_batch: list[Document] = []


        for doc in documents_from_postgres:
            doc_batch.append(doc)

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_postgres()

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._process_postgres(start_datetime, end_datetime)


if __name__ == "__main__":

    connector = PostgresConnector(content_columns=["column1"], metadata_columns=["column2", "column3"],
                                  query="SELECT * FROM \"some\";")
    connector.load_credentials({"host": "localhost", "password": "some-pass", "database": "test-as"})

    for batch in connector.load_from_state():
        for document in batch:
            print(document)
