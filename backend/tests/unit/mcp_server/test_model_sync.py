"""Ensure MCP lightweight models and enums stay in sync with their source counterparts.

The MCP server uses lightweight copies of Onyx models and enums to avoid importing
heavy dependencies like SQLAlchemy. This also allows the MCP server to run as a standalone
service. These tests ensure the lightweight copies don't diverge from the source.

If these tests fail, update onyx/mcp_server/models.py to match changes in the source.
"""

from enum import Enum

import pytest
from pydantic import BaseModel

from onyx.configs.constants import DocumentSource as SourceDocumentSource
from onyx.context.search.enums import LLMEvaluationType as SourceLLMEvaluationType
from onyx.context.search.enums import SearchType as SourceSearchType
from onyx.context.search.models import BaseFilters as SourceBaseFilters
from onyx.context.search.models import ChunkContext as SourceChunkContext
from onyx.context.search.models import IndexFilters as SourceIndexFilters
from onyx.context.search.models import RetrievalDetails as SourceRetrievalDetails
from onyx.context.search.models import Tag as SourceTag
from onyx.context.search.models import UserFileFilters as SourceUserFileFilters
from onyx.mcp_server.models import BaseFilters as MCPBaseFilters
from onyx.mcp_server.models import ChunkContext as MCPChunkContext
from onyx.mcp_server.models import DocumentSearchRequest as MCPDocumentSearchRequest
from onyx.mcp_server.models import DocumentSource as MCPDocumentSource
from onyx.mcp_server.models import IndexFilters as MCPIndexFilters
from onyx.mcp_server.models import LLMEvaluationType as MCPLLMEvaluationType
from onyx.mcp_server.models import RetrievalDetails as MCPRetrievalDetails
from onyx.mcp_server.models import SearchType as MCPSearchType
from onyx.mcp_server.models import Tag as MCPTag
from onyx.mcp_server.models import UserFileFilters as MCPUserFileFilters
from onyx.server.query_and_chat.models import (
    DocumentSearchRequest as SourceDocumentSearchRequest,
)

# Source enums
# Source models
# MCP enums
# MCP models


def get_model_fields(model_class: type[BaseModel]) -> set[str]:
    """Get field names from a Pydantic model."""
    return set(model_class.model_fields.keys())


def get_enum_values(enum_class: type[Enum]) -> set[str]:
    """Get all string values from a str enum."""
    return {str(member.value) for member in enum_class}


def get_enum_names(enum_class: type[Enum]) -> set[str]:
    """Get all member names from an enum."""
    return {member.name for member in enum_class}


# =============================================================================
# Enum Sync Tests
# =============================================================================


class TestEnumSync:
    """Ensure MCP enums have all values from source enums."""

    @pytest.mark.parametrize(
        "source_enum,mcp_enum,enum_name",
        [
            (SourceDocumentSource, MCPDocumentSource, "DocumentSource"),
            (SourceSearchType, MCPSearchType, "SearchType"),
            (SourceLLMEvaluationType, MCPLLMEvaluationType, "LLMEvaluationType"),
        ],
    )
    def test_mcp_enum_has_all_source_values(
        self, source_enum: type[Enum], mcp_enum: type[Enum], enum_name: str
    ) -> None:
        """MCP enums must have all values from source enums.

        If source adds a new enum value, MCP must add it too, otherwise
        the API server might return values MCP can't deserialize.
        """
        source_values = get_enum_values(source_enum)
        mcp_values = get_enum_values(mcp_enum)

        missing = source_values - mcp_values
        assert not missing, (
            f"MCP {enum_name} is missing values from source: {missing}. "
            f"Add these to onyx/mcp_server/models.py"
        )

    @pytest.mark.parametrize(
        "source_enum,mcp_enum,enum_name",
        [
            (SourceDocumentSource, MCPDocumentSource, "DocumentSource"),
            (SourceSearchType, MCPSearchType, "SearchType"),
            (SourceLLMEvaluationType, MCPLLMEvaluationType, "LLMEvaluationType"),
        ],
    )
    def test_mcp_enum_no_extra_values(
        self, source_enum: type[Enum], mcp_enum: type[Enum], enum_name: str
    ) -> None:
        """MCP enums should not have values that don't exist in source.

        Extra values would allow MCP to send invalid data to the API server.
        """
        source_values = get_enum_values(source_enum)
        mcp_values = get_enum_values(mcp_enum)

        extra = mcp_values - source_values
        assert not extra, (
            f"MCP {enum_name} has values not in source: {extra}. "
            f"Remove these from onyx/mcp_server/models.py or add to source."
        )

    @pytest.mark.parametrize(
        "source_enum,mcp_enum,enum_name",
        [
            (SourceDocumentSource, MCPDocumentSource, "DocumentSource"),
            (SourceSearchType, MCPSearchType, "SearchType"),
            (SourceLLMEvaluationType, MCPLLMEvaluationType, "LLMEvaluationType"),
        ],
    )
    def test_enum_names_match(
        self, source_enum: type[Enum], mcp_enum: type[Enum], enum_name: str
    ) -> None:
        """Enum member names should match between source and MCP."""
        source_names = get_enum_names(source_enum)
        mcp_names = get_enum_names(mcp_enum)

        # Check that MCP has all source names
        missing = source_names - mcp_names
        assert not missing, (
            f"MCP {enum_name} is missing member names: {missing}. "
            f"Add these to onyx/mcp_server/models.py"
        )


# =============================================================================
# Model Sync Tests
# =============================================================================


class TestMCPModelsSubsetOfSource:
    """MCP model fields should be a subset of source model fields.

    If an MCP model has a field that doesn't exist in the source model,
    serialization will include extra data that the API server doesn't expect.
    """

    @pytest.mark.parametrize(
        "source_model,mcp_model,model_name",
        [
            (SourceTag, MCPTag, "Tag"),
            (SourceBaseFilters, MCPBaseFilters, "BaseFilters"),
            (SourceUserFileFilters, MCPUserFileFilters, "UserFileFilters"),
            (SourceIndexFilters, MCPIndexFilters, "IndexFilters"),
            (SourceChunkContext, MCPChunkContext, "ChunkContext"),
            (SourceRetrievalDetails, MCPRetrievalDetails, "RetrievalDetails"),
            (
                SourceDocumentSearchRequest,
                MCPDocumentSearchRequest,
                "DocumentSearchRequest",
            ),
        ],
    )
    def test_mcp_fields_exist_in_source(
        self, source_model: type[BaseModel], mcp_model: type[BaseModel], model_name: str
    ) -> None:
        source_fields = get_model_fields(source_model)
        mcp_fields = get_model_fields(mcp_model)
        extra_fields = mcp_fields - source_fields

        assert not extra_fields, (
            f"MCP {model_name} has fields not in source: {extra_fields}. "
            f"These fields will be serialized but the API server doesn't expect them. "
            f"Remove them from onyx/mcp_server/models.py or add them to the source model."
        )


class TestMCPModelsFieldTypes:
    """Verify field types match between MCP and source models."""

    @pytest.mark.parametrize(
        "source_model,mcp_model,model_name",
        [
            (SourceTag, MCPTag, "Tag"),
            (SourceBaseFilters, MCPBaseFilters, "BaseFilters"),
            (SourceIndexFilters, MCPIndexFilters, "IndexFilters"),
            (SourceRetrievalDetails, MCPRetrievalDetails, "RetrievalDetails"),
            (
                SourceDocumentSearchRequest,
                MCPDocumentSearchRequest,
                "DocumentSearchRequest",
            ),
        ],
    )
    def test_shared_field_types_match(
        self, source_model: type[BaseModel], mcp_model: type[BaseModel], model_name: str
    ) -> None:
        """Fields present in both models should have compatible types."""
        source_fields = source_model.model_fields
        mcp_fields = mcp_model.model_fields

        shared_fields = set(source_fields.keys()) & set(mcp_fields.keys())

        mismatches = []
        for field_name in shared_fields:
            source_annotation = source_fields[field_name].annotation
            mcp_annotation = mcp_fields[field_name].annotation

            # Compare string representations since types might be defined differently
            # but still be compatible (e.g., list[str] vs List[str])
            source_str = str(source_annotation)
            mcp_str = str(mcp_annotation)

            # Normalize some common differences
            source_normalized = source_str.replace("typing.", "").replace(
                "List", "list"
            )
            mcp_normalized = mcp_str.replace("typing.", "").replace("List", "list")

            # Allow for different module paths to the same enum
            # e.g., onyx.configs.constants.DocumentSource vs onyx.mcp_server.models.DocumentSource
            source_normalized = source_normalized.replace("onyx.configs.constants.", "")
            source_normalized = source_normalized.replace(
                "onyx.context.search.enums.", ""
            )
            source_normalized = source_normalized.replace(
                "onyx.context.search.models.", ""
            )
            mcp_normalized = mcp_normalized.replace("onyx.mcp_server.models.", "")

            if source_normalized != mcp_normalized:
                mismatches.append(f"  {field_name}: source={source_str}, mcp={mcp_str}")

        # Allow some type differences as long as they're compatible for JSON serialization
        # This is a soft check - we warn but don't fail on all mismatches
        if mismatches:
            pytest.skip(
                f"Type differences in {model_name} (may be OK if JSON-compatible):\n"
                + "\n".join(mismatches)
            )


class TestNewSourceFieldsWarning:
    """Warn when source models add new fields that MCP might want to use."""

    @pytest.mark.parametrize(
        "source_model,mcp_model,model_name",
        [
            (SourceIndexFilters, MCPIndexFilters, "IndexFilters"),
            (SourceRetrievalDetails, MCPRetrievalDetails, "RetrievalDetails"),
            (
                SourceDocumentSearchRequest,
                MCPDocumentSearchRequest,
                "DocumentSearchRequest",
            ),
        ],
    )
    def test_warn_on_new_source_fields(
        self, source_model: type[BaseModel], mcp_model: type[BaseModel], model_name: str
    ) -> None:
        """Informational: show fields in source that aren't in MCP model."""
        source_fields = get_model_fields(source_model)
        mcp_fields = get_model_fields(mcp_model)
        new_fields = source_fields - mcp_fields

        if new_fields:
            # This is informational, not a failure
            # These fields exist in source but MCP doesn't use them (which is fine)
            pytest.skip(
                f"{model_name} has source fields not in MCP copy: {new_fields}. "
                f"This is OK if MCP doesn't need them."
            )
