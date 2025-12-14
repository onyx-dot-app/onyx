"""
Pytest fixtures and factory functions for Coda connector tests.

This module provides reusable factory functions to create test objects
with sensible defaults, reducing boilerplate in test files.
"""

from random import randint
from typing import Any

from onyx.connectors.coda.models.column_formats import CodaColumnFormatType
from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.folder import CodaFolderReference
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.page import CodaPageContentType
from onyx.connectors.coda.models.page import CodaPageReference
from onyx.connectors.coda.models.table.column import CodaColumn
from onyx.connectors.coda.models.table.column import CodaColumnFormat
from onyx.connectors.coda.models.table.row import CodaRow
from onyx.connectors.coda.models.table.table import CodaTableReference
from onyx.connectors.coda.models.table.table import TableType
from onyx.connectors.coda.models.workspace import CodaWorkspaceReference


def make_doc(
    **params: Any | CodaDoc,
) -> CodaDoc:
    """
    Factory function to create a CodaDoc with sensible defaults.

    Args:
        **params: Additional fields to override defaults

    Returns:
        CodaDoc instance
    """

    random_number = randint(1, 100)
    default_id = f"doc-{random_number}"
    default_name = f"Test Document {random_number}"
    defaults: CodaDoc = {
        "id": default_id,
        "href": f"https://coda.io/apis/v1/docs/{default_id}",
        "name": default_name,
        "browserLink": f"https://coda.io/d/{default_id}",
        "type": CodaObjectType.DOC,
        "owner": "test@example.com",
        "ownerName": "Test Owner",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-02T00:00:00Z",
        "workspace": make_workspace_ref(),
        "folder": make_folder_ref(),
    }
    final_params = {**defaults, **params}

    return CodaDoc(**final_params)


def make_page(
    **params: Any | CodaPage,
) -> CodaPage:
    """
    Factory function to create a CodaPage with sensible defaults.

    Args:
        **params: Additional fields to override defaults

    Returns:
        CodaPage instance
    """
    random_number = randint(1, 100)
    default_id = f"page-{random_number}"
    default_name = f"Test Page {random_number}"

    defaults: CodaPage = {
        "id": default_id,
        "name": default_name,
        "href": f"https://coda.io/apis/v1/docs/{default_id}/pages/{default_id}",
        "browserLink": f"https://coda.io/d/{default_id}/{default_id}",
        "type": CodaObjectType.PAGE,
        "isHidden": False,
        "isEffectivelyHidden": False,
        "children": [],
        "contentType": CodaPageContentType.CANVAS,
    }
    final_params = {**defaults, **params}
    return CodaPage(**final_params)


def make_page_ref(
    **params: Any | CodaPageReference,
) -> CodaPageReference:
    """
    Factory function to create a CodaPageReference with sensible defaults.

    Args:
        **params: Additional fields to override defaults

    Returns:
        CodaPageReference instance
    """

    defaults: CodaPageReference = {
        "browserLink": "https://coda.io/d",
        "type": CodaObjectType.PAGE,
    }

    final_params = {**defaults, **params}
    return CodaPageReference(**final_params)


def make_table_ref(
    **params: Any | CodaTableReference,
) -> CodaTableReference:
    """
    Factory function to create a CodaTableReference with sensible defaults.

    Args:
        **params: Additional fields to override defaults

    Returns:
        CodaTableReference instance
    """
    defaults = {
        "browserLink": "https://coda.io/d",
        "type": CodaObjectType.TABLE,
        "tableType": TableType.TABLE,
    }

    final_params = {**defaults, **params}
    return CodaTableReference(**final_params)


def make_column_format(
    **params: Any | CodaColumnFormat,
) -> CodaColumnFormat:
    """
    Factory function to create a CodaColumnFormat with sensible defaults.

    Args:
        **params: Additional fields to override defaults

    Returns:
        CodaColumnFormat instance
    """
    defaults = {
        "type": CodaColumnFormatType.TEXT,
        "isArray": False,
    }
    final_params = {**defaults, **params}
    return CodaColumnFormat(**final_params)


def make_column(
    **params: Any | CodaColumn,
) -> CodaColumn:
    """
    Factory function to create a CodaColumn with sensible defaults.

    Args:
        **params: Additional fields to override defaults

    Returns:
        CodaColumn instance
    """
    random_number = randint(1, 100)
    default_id = f"column-{random_number}"
    default_name = f"Test Column {random_number}"
    defaults = {
        "id": default_id,
        "name": default_name,
        "href": "https://coda.io",
        "type": CodaObjectType.COLUMN,
        "display": True,
        "format": make_column_format(),
    }
    final_params = {**defaults, **params}
    return CodaColumn(**final_params)


def make_row(
    **params: Any | CodaRow,
) -> CodaRow:
    """
    Factory function to create a CodaRow with sensible defaults.

    Args:
        **kwargs: Additional fields to override defaults

    Returns:
        CodaRow instance
    """
    random_number = randint(1, 100)
    default_id = f"row-{random_number}"
    default_name = f"Test Row {random_number}"
    defaults = {
        "id": default_id,
        "name": default_name,
        "href": "https://coda.io",
        "type": CodaObjectType.ROW,
        "index": random_number,
        "browserLink": "https://coda.io",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "values": {},
        "parent": make_table_ref(),
    }
    final_params = {**defaults, **params}
    return CodaRow(**final_params)


def make_workspace_ref(
    **params: Any | CodaWorkspaceReference,
) -> CodaWorkspaceReference:
    """
    Factory function to create a CodaWorkspaceReference with sensible defaults.

    Args:
        **params: Additional fields to override defaults

    Returns:
        CodaWorkspaceReference instance
    """
    random_number = randint(1, 100)
    default_id = f"workspace-{random_number}"
    default_name = f"Test Workspace {random_number}"

    defaults = {
        "id": default_id,
        "type": "workspace",
        "browserLink": "https://coda.io/w/{id}",
        "organizationId": "test@example.com",
        "name": default_name,
    }
    final_params = {**defaults, **params}
    return CodaWorkspaceReference(**final_params)


def make_folder_ref(
    **params: Any | CodaFolderReference,
) -> CodaFolderReference:
    """
    Factory function to create a CodaFolderReference with sensible defaults.

    Args:
        **kwargs: Additional fields to override defaults

    Returns:
        CodaFolderReference instance
    """

    random_number = randint(1, 100)
    default_id = f"folder-{random_number}"
    default_name = f"Test Folder {random_number}"

    defaults = {
        "id": default_id,
        "type": "folder",
        "browserLink": f"https://coda.io/f/{default_id}",
        "name": default_name,
    }

    final_params = {**defaults, **params}
    return CodaFolderReference(**final_params)
