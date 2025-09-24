from datetime import datetime
from datetime import timedelta
from datetime import timezone
from uuid import UUID

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import INDEX_SEPARATOR
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import Tag
from onyx.document_index.vespa.shared_utils.vespa_request_builders import (
    build_vespa_filters,
)
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_ID
from onyx.document_index.vespa_constants import DOCUMENT_SETS
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import METADATA_LIST
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TENANT_ID
from onyx.document_index.vespa_constants import USER_PROJECT
from shared_configs.configs import MULTI_TENANT

# Import the function under test


class TestBuildVespaFilters:
    def test_empty_filters(self) -> None:
        """Test with empty filters object."""
        filters = IndexFilters(access_control_list=[])
        result = build_vespa_filters(filters)
        assert result == f"!({HIDDEN}=true) and "

        # With trailing AND removed
        result = build_vespa_filters(filters, remove_trailing_and=True)
        assert result == f"!({HIDDEN}=true)"

    def test_include_hidden(self) -> None:
        """Test with include_hidden flag."""
        filters = IndexFilters(access_control_list=[])
        result = build_vespa_filters(filters, include_hidden=True)
        assert result == ""  # No filters applied when including hidden

        # With some other filter to ensure proper AND chaining
        filters = IndexFilters(access_control_list=[], source_type=[DocumentSource.WEB])
        result = build_vespa_filters(filters, include_hidden=True)
        assert result == f'({SOURCE_TYPE} contains "web") and '

    def test_acl(self) -> None:
        """Test with acls."""
        # Single ACL
        filters = IndexFilters(access_control_list=["user1"])
        result = build_vespa_filters(filters)
        assert (
            result
            == f'!({HIDDEN}=true) and (access_control_list contains "user1") and '
        )

        # Multiple ACL's
        filters = IndexFilters(access_control_list=["user2", "group2"])
        result = build_vespa_filters(filters)
        assert (
            result
            == f'!({HIDDEN}=true) and (access_control_list contains "user2" or access_control_list contains "group2") and '
        )

    def test_tenant_filter(self) -> None:
        """Test tenant ID filtering."""
        # With tenant ID
        if MULTI_TENANT:
            filters = IndexFilters(access_control_list=[], tenant_id="tenant1")
            result = build_vespa_filters(filters)
            assert (
                f'!({HIDDEN}=true) and ({TENANT_ID} contains "tenant1") and ' == result
            )

        # No tenant ID
        filters = IndexFilters(access_control_list=[], tenant_id=None)
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

    def test_source_type_filter(self) -> None:
        """Test source type filtering."""
        # Single source type
        filters = IndexFilters(access_control_list=[], source_type=[DocumentSource.WEB])
        result = build_vespa_filters(filters)
        assert f'!({HIDDEN}=true) and ({SOURCE_TYPE} contains "web") and ' == result

        # Multiple source types
        filters = IndexFilters(
            access_control_list=[],
            source_type=[DocumentSource.WEB, DocumentSource.JIRA],
        )
        result = build_vespa_filters(filters)
        assert (
            f'!({HIDDEN}=true) and ({SOURCE_TYPE} contains "web" or {SOURCE_TYPE} contains "jira") and '
            == result
        )

        # Empty source type list
        filters = IndexFilters(access_control_list=[], source_type=[])
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

    def test_tag_filters(self) -> None:
        """Test tag filtering."""
        # Single tag
        filters = IndexFilters(
            access_control_list=[], tags=[Tag(tag_key="color", tag_value="red")]
        )
        result = build_vespa_filters(filters)
        assert (
            f'!({HIDDEN}=true) and ({METADATA_LIST} contains "color{INDEX_SEPARATOR}red") and '
            == result
        )

        # Multiple tags
        filters = IndexFilters(
            access_control_list=[],
            tags=[
                Tag(tag_key="color", tag_value="red"),
                Tag(tag_key="size", tag_value="large"),
            ],
        )
        result = build_vespa_filters(filters)
        expected = (
            f'!({HIDDEN}=true) and ({METADATA_LIST} contains "color{INDEX_SEPARATOR}red" '
            f'or {METADATA_LIST} contains "size{INDEX_SEPARATOR}large") and '
        )
        assert expected == result

        # Empty tags list
        filters = IndexFilters(access_control_list=[], tags=[])
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

    def test_document_sets_filter(self) -> None:
        """Test document sets filtering."""
        # Single document set
        filters = IndexFilters(access_control_list=[], document_set=["set1"])
        result = build_vespa_filters(filters)
        assert f'!({HIDDEN}=true) and ({DOCUMENT_SETS} contains "set1") and ' == result

        # Multiple document sets
        filters = IndexFilters(access_control_list=[], document_set=["set1", "set2"])
        result = build_vespa_filters(filters)
        assert (
            f'!({HIDDEN}=true) and ({DOCUMENT_SETS} contains "set1" or {DOCUMENT_SETS} contains "set2") and '
            == result
        )

        # Empty document sets
        filters = IndexFilters(access_control_list=[], document_set=[])
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

    def test_user_file_ids_filter(self) -> None:
        """Test user file IDs filtering."""
        id1 = UUID("00000000-0000-0000-0000-000000000123")
        id2 = UUID("00000000-0000-0000-0000-000000000456")

        # Single user file ID (UUID)
        filters = IndexFilters(access_control_list=[], user_file_ids=[id1])
        result = build_vespa_filters(filters)
        assert (
            f'!({HIDDEN}=true) and ({DOCUMENT_ID} contains "{str(id1)}") and ' == result
        )

        # Multiple user file IDs (UUIDs)
        filters = IndexFilters(access_control_list=[], user_file_ids=[id1, id2])
        result = build_vespa_filters(filters)
        assert (
            f'!({HIDDEN}=true) and ({DOCUMENT_ID} contains "{str(id1)}" or {DOCUMENT_ID} contains "{str(id2)}") and '
            == result
        )

        # Empty user file IDs
        filters = IndexFilters(access_control_list=[], user_file_ids=[])
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

    def test_user_project_filter(self) -> None:
        """Test user project filtering (replacement for user folder IDs)."""
        # Single project id
        filters = IndexFilters(access_control_list=[], project_id=789)
        result = build_vespa_filters(filters)
        assert f'!({HIDDEN}=true) and ({USER_PROJECT} contains "789") and ' == result

        # No project id
        filters = IndexFilters(access_control_list=[], project_id=None)
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

    def test_time_cutoff_filter(self) -> None:
        """Test time cutoff filtering."""
        # With cutoff time
        cutoff_time = datetime(2023, 1, 1, tzinfo=timezone.utc)
        filters = IndexFilters(access_control_list=[], time_cutoff=cutoff_time)
        result = build_vespa_filters(filters)
        cutoff_secs = int(cutoff_time.timestamp())
        assert (
            f"!({HIDDEN}=true) and !({DOC_UPDATED_AT} < {cutoff_secs}) and " == result
        )

        # No cutoff time
        filters = IndexFilters(access_control_list=[], time_cutoff=None)
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

        # Test untimed logic (when cutoff is old enough)
        old_cutoff = datetime.now(timezone.utc) - timedelta(days=100)
        filters = IndexFilters(access_control_list=[], time_cutoff=old_cutoff)
        result = build_vespa_filters(filters)
        old_cutoff_secs = int(old_cutoff.timestamp())
        assert (
            f"!({HIDDEN}=true) and !({DOC_UPDATED_AT} < {old_cutoff_secs}) and "
            == result
        )

    def test_combined_filters(self) -> None:
        """Test combining multiple filter types."""
        id1 = UUID("00000000-0000-0000-0000-000000000123")
        filters = IndexFilters(
            access_control_list=["user1", "group1"],
            source_type=[DocumentSource.WEB],
            tags=[Tag(tag_key="color", tag_value="red")],
            document_set=["set1"],
            user_file_ids=[id1],
            project_id=789,
            time_cutoff=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )

        result = build_vespa_filters(filters)

        # Build expected result piece by piece for readability
        expected = f"!({HIDDEN}=true) and "
        expected += (
            '(access_control_list contains "user1" or '
            'access_control_list contains "group1") and '
        )
        expected += f'({SOURCE_TYPE} contains "web") and '
        expected += f'({METADATA_LIST} contains "color{INDEX_SEPARATOR}red") and '
        expected += f'({DOCUMENT_SETS} contains "set1") and '
        expected += f'({DOCUMENT_ID} contains "{str(id1)}") and '
        expected += f'({USER_PROJECT} contains "789") and '
        cutoff_secs = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
        expected += f"!({DOC_UPDATED_AT} < {cutoff_secs}) and "

        assert expected == result

        # With trailing AND removed
        result_no_trailing = build_vespa_filters(filters, remove_trailing_and=True)
        assert expected[:-5] == result_no_trailing  # Remove trailing " and "

    def test_empty_or_none_values(self) -> None:
        """Test with empty or None values in filter lists."""
        # Empty strings in document set
        filters = IndexFilters(
            access_control_list=[], document_set=["set1", "", "set2"]
        )
        result = build_vespa_filters(filters)
        assert (
            f'!({HIDDEN}=true) and ({DOCUMENT_SETS} contains "set1" or {DOCUMENT_SETS} contains "set2") and '
            == result
        )

        # All empty strings in document set
        filters = IndexFilters(access_control_list=[], document_set=["", ""])
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result
