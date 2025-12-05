"""
Pytest fixtures and factory functions for Coda connector tests.

This module provides reusable factory functions to create test objects
with sensible defaults, reducing boilerplate in test files.
"""

from typing import Any

from onyx.connectors.coda.models.common import CodaObjectType
from onyx.connectors.coda.models.doc import CodaDoc
from onyx.connectors.coda.models.folder import CodaFolderReference
from onyx.connectors.coda.models.page import CodaPage
from onyx.connectors.coda.models.page import CodaPageReference
from onyx.connectors.coda.models.table import CodaColumn
from onyx.connectors.coda.models.table import CodaColumnFormat
from onyx.connectors.coda.models.table import CodaColumnFormatType
from onyx.connectors.coda.models.table import CodaRow
from onyx.connectors.coda.models.table import CodaTableReference
from onyx.connectors.coda.models.table import TableType
from onyx.connectors.coda.models.workspace import CodaWorkspaceReference


def make_doc(
    id: str = "doc-1",
    name: str = "Test Document",
    **kwargs: Any,
) -> CodaDoc:
    """
    Factory function to create a CodaDoc with sensible defaults.

    Args:
        id: Document ID (default: "doc-1")
        name: Document name (default: "Test Document")
        **kwargs: Additional fields to override defaults

    Returns:
        CodaDoc instance
    """
    defaults = {
        "href": f"https://coda.io/apis/v1/docs/{id}",
        "browserLink": f"https://coda.io/d/{id}",
        "type": "doc",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-02T00:00:00Z",
        "owner": "test@example.com",
        "ownerName": "Test Owner",
        "workspace": make_workspace_ref(),
        "folder": make_folder_ref(),
    }
    defaults.update(kwargs)
    return CodaDoc(id=id, name=name, **defaults)


def make_page(
    id: str = "page-1",
    name: str = "Test Page",
    doc_id: str = "doc-1",
    **kwargs: Any,
) -> CodaPage:
    """
    Factory function to create a CodaPage with sensible defaults.

    Args:
        id: Page ID (default: "page-1")
        name: Page name (default: "Test Page")
        doc_id: Parent document ID (default: "doc-1")
        **kwargs: Additional fields to override defaults

    Returns:
        CodaPage instance
    """
    defaults = {
        "href": f"https://coda.io/apis/v1/docs/{doc_id}/pages/{id}",
        "browserLink": f"https://coda.io/d/{doc_id}/{id}",
        "type": CodaObjectType.PAGE,
        "isHidden": False,
        "isEffectivelyHidden": False,
        "children": [],
        "contentType": "canvas",
    }
    defaults.update(kwargs)
    return CodaPage(id=id, name=name, **defaults)


def make_page_ref(
    id: str = "page-1",
    name: str = "Test Page",
    doc_id: str = "doc-1",
    **kwargs: Any,
) -> CodaPageReference:
    """
    Factory function to create a CodaPageReference with sensible defaults.

    Args:
        id: Page ID (default: "page-1")
        name: Page name (default: "Test Page")
        doc_id: Parent document ID (default: "doc-1")
        **kwargs: Additional fields to override defaults

    Returns:
        CodaPageReference instance
    """
    defaults = {
        "href": f"https://coda.io/apis/v1/docs/{doc_id}/pages/{id}",
        "browserLink": f"https://coda.io/d/{doc_id}/{id}",
        "type": CodaObjectType.PAGE,
    }
    defaults.update(kwargs)
    return CodaPageReference(id=id, name=name, **defaults)


def make_table(
    id: str = "table-1",
    name: str = "Test Table",
    doc_id: str = "doc-1",
    **kwargs: Any,
) -> CodaTableReference:
    """
    Factory function to create a CodaTableReference with sensible defaults.

    Args:
        id: Table ID (default: "table-1")
        name: Table name (default: "Test Table")
        doc_id: Parent document ID (default: "doc-1")
        **kwargs: Additional fields to override defaults

    Returns:
        CodaTableReference instance
    """
    defaults = {
        "href": f"https://coda.io/apis/v1/docs/{doc_id}/tables/{id}",
        "browserLink": f"https://coda.io/d/{doc_id}/{id}",
        "type": CodaObjectType.TABLE,
        "tableType": TableType.TABLE,
    }
    defaults.update(kwargs)
    return CodaTableReference(id=id, name=name, **defaults)


def make_column(
    id: str = "col-1",
    name: str = "Column",
    table_id: str = "table-1",
    doc_id: str = "doc-1",
    format_type: CodaColumnFormatType = CodaColumnFormatType.text,
    **kwargs: Any,
) -> CodaColumn:
    """
    Factory function to create a CodaColumn with sensible defaults.

    Args:
        id: Column ID (default: "col-1")
        name: Column name (default: "Column")
        table_id: Parent table ID (default: "table-1")
        doc_id: Parent document ID (default: "doc-1")
        format_type: Column format type (default: text)
        **kwargs: Additional fields to override defaults

    Returns:
        CodaColumn instance
    """
    defaults = {
        "type": CodaObjectType.COLUMN,
        "href": f"https://coda.io/apis/v1/docs/{doc_id}/tables/{table_id}/columns/{id}",
        "format": CodaColumnFormat(type=format_type, isArray=False),
        "display": True,
    }
    defaults.update(kwargs)
    return CodaColumn(id=id, name=name, **defaults)


def make_row(
    id: str = "row-1",
    name: str = "Row 1",
    table_id: str = "table-1",
    doc_id: str = "doc-1",
    index: int = 0,
    values: dict[str, Any] | None = None,
    **kwargs: Any,
) -> CodaRow:
    """
    Factory function to create a CodaRow with sensible defaults.

    Args:
        id: Row ID (default: "row-1")
        name: Row name (default: "Row 1")
        table_id: Parent table ID (default: "table-1")
        doc_id: Parent document ID (default: "doc-1")
        index: Row index (default: 0)
        values: Cell values dict (default: {})
        **kwargs: Additional fields to override defaults

    Returns:
        CodaRow instance
    """
    defaults = {
        "href": f"https://coda.io/apis/v1/docs/{doc_id}/tables/{table_id}/rows/{id}",
        "type": CodaObjectType.ROW,
        "browserLink": f"https://coda.io/d/{doc_id}/{table_id}/{id}",
        "createdAt": "2024-01-01T00:00:00Z",
        "updatedAt": "2024-01-01T00:00:00Z",
        "values": values or {},
    }
    defaults.update(kwargs)
    return CodaRow(id=id, name=name, index=index, **defaults)


def make_workspace_ref(
    id: str = "workspace-1",
    **kwargs: Any,
) -> CodaWorkspaceReference:
    """
    Factory function to create a CodaWorkspaceReference with sensible defaults.

    Args:
        id: Workspace ID (default: "workspace-1")
        **kwargs: Additional fields to override defaults

    Returns:
        CodaWorkspaceReference instance
    """
    defaults = {
        "type": "workspace",
        "browserLink": f"https://coda.io/w/{id}",
    }
    defaults.update(kwargs)
    return CodaWorkspaceReference(id=id, **defaults)


def make_folder_ref(
    id: str = "folder-1",
    name: str = "Test Folder",
    **kwargs: Any,
) -> CodaFolderReference:
    """
    Factory function to create a CodaFolderReference with sensible defaults.

    Args:
        id: Folder ID (default: "folder-1")
        name: Folder name (default: "Test Folder")
        **kwargs: Additional fields to override defaults

    Returns:
        CodaFolderReference instance
    """
    defaults = {
        "type": "folder",
        "browserLink": f"https://coda.io/f/{id}",
    }
    defaults.update(kwargs)
    return CodaFolderReference(id=id, name=name, **defaults)
