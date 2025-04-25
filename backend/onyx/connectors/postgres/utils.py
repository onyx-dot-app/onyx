from datetime import datetime
from uuid import uuid4

import psycopg2
from psycopg2 import sql
from typing import List, Dict, Optional

from onyx.configs.constants import DocumentSource
from onyx.connectors.models import TextSection
from onyx.connectors.models import Document


class PostgreSQLUtility:
    def __init__(
            self,
            host: str,
            port: int = 5432,
            db_name: str = "postgres",
            user: str = "postgres",
            password: Optional[str] = None
    ):
        self.host = host
        self.port = port
        self.db_name = db_name
        self.user = user
        self.password = password
        self.connection = None

    def connect(self):
        try:
            self.connection = psycopg2.connect(
                host=self.host,
                port=self.port,
                dbname=self.db_name,
                user=self.user,
                password=self.password
            )
        except psycopg2.Error as e:
            raise ConnectionError(f"Ошибка подключения к PostgreSQL: {e}")

    def fetch_documents(
            self,
            table_name: str | None = None,
            query: str | None = None,
            content_columns: Optional[List[str]] = None,
            metadata_columns: Optional[List[str]] = None
    ) -> list[Document]:
        if not self.connection:
            self.connect()

        if table_name and query:
            raise ValueError("Укажите либо table_name, либо query, но не оба")
        if not table_name and not query:
            raise ValueError("Необходимо указать table_name или query")

        documents = []
        with self.connection.cursor() as cursor:
            if table_name:
                query, column_names = self._build_table_query(cursor,
                    table_name, content_columns, metadata_columns
                )
            else:
                column_names = self._execute_custom_query(cursor, query)

            for row in cursor.fetchall():
                content, metadata, updated_at = self._process_row(
                    row,
                    column_names,
                    content_columns,
                    metadata_columns
                )
                if not updated_at:
                    updated_at = datetime.now()
                doc = Document(
                    id=str(uuid4()),
                    sections=[TextSection(link="", text=content)],
                    semantic_identifier=" ".join(column_names),
                    doc_updated_at=updated_at,
                    metadata=metadata,
                    source=DocumentSource.POSTGRES,
                )
                documents.append(doc)

        return documents

    def _build_table_query(self, cursor, table_name, content_cols, metadata_cols):
        cursor.execute(f"""
            SELECT column_name 
            FROM information_schema.columns 
            WHERE table_name = '{table_name}'
        """)
        table_columns = [row[0] for row in cursor.fetchall()]

        columns_to_select = []
        if content_cols:
            columns_to_select.extend(content_cols)
        if metadata_cols:
            columns_to_select.extend(metadata_cols)

        if "updated_at" in table_columns and "updated_at" not in columns_to_select:
            columns_to_select.append("updated_at")

        query = sql.SQL("SELECT {} FROM {}").format(
            sql.SQL(", ").join(map(sql.Identifier, columns_to_select)),
            sql.Identifier(table_name)
        )
        cursor.execute(query)

        return query, columns_to_select

    def _execute_custom_query(self, cursor, query):
        try:
            cursor.execute(query)
        except psycopg2.errors.SyntaxError as e:
            raise SyntaxError(e)
        return [desc[0] for desc in cursor.description]

    def _process_row(self, row, column_names, content_cols, metadata_cols):
        if content_cols:
            missing = [col for col in content_cols if col not in column_names]
            if missing:
                raise ValueError(f"Content columns not found: {', '.join(missing)}")

        if metadata_cols:
            missing = [col for col in metadata_cols if col not in column_names]
            if missing:
                raise ValueError(f"Metadata columns not found: {', '.join(missing)}")

        try:
            if content_cols:
                content_indices = [column_names.index(col) for col in content_cols]
                content = " ".join(str(row[i]) for i in content_indices)
                used_indices = set(content_indices)
            else:
                content = str(row[0])
                used_indices = {0}

            metadata = {}
            if metadata_cols:
                for col in metadata_cols:
                    idx = column_names.index(col)
                    metadata[col] = str(row[idx])
                    used_indices.add(idx)

            updated_at = None
            if "updated_at" in column_names:
                updated_at_idx = column_names.index("updated_at")
                updated_at = row[updated_at_idx]


        except (IndexError, ValueError) as e:
            raise RuntimeError(f"Error processing row: {str(e)}") from e

        return content, metadata, updated_at

    def close(self):
        if self.connection:
            self.connection.close()