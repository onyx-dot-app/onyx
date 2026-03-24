from datetime import datetime
from datetime import timedelta
from datetime import timezone

from onyx.configs.constants import DocumentSource
from onyx.configs.constants import INDEX_SEPARATOR
from onyx.context.search.models import IndexFilters
from onyx.context.search.models import Tag
from onyx.document_index.vespa.shared_utils.vespa_request_builders import (
    build_vespa_filters,
)
from onyx.document_index.vespa_constants import DOC_UPDATED_AT
from onyx.document_index.vespa_constants import DOCUMENT_SETS
from onyx.document_index.vespa_constants import HIDDEN
from onyx.document_index.vespa_constants import METADATA_LIST
from onyx.document_index.vespa_constants import PERSONAS
from onyx.document_index.vespa_constants import SOURCE_TYPE
from onyx.document_index.vespa_constants import TENANT_ID
from onyx.document_index.vespa_constants import USER_PROJECT
from shared_configs.configs import MULTI_TENANT


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
        """Test with acls — uses weightedSet operator for efficient matching."""
        # Single ACL
        filters = IndexFilters(access_control_list=["user1"])
        result = build_vespa_filters(filters)
        assert (
            result
            == f'!({HIDDEN}=true) and weightedSet(access_control_list, {{"user1":1}}) and '
        )

        # Multiple ACL's
        filters = IndexFilters(access_control_list=["user2", "group2"])
        result = build_vespa_filters(filters)
        assert (
            result
            == f'!({HIDDEN}=true) and weightedSet(access_control_list, {{"user2":1, "group2":1}}) and '
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

    def test_user_project_filter(self) -> None:
        """Test user project filtering.

        project_id alone does NOT trigger a knowledge scope restriction
        (an agent with no explicit knowledge should search everything).
        It only participates when explicit knowledge filters are present.
        """
        # project_id alone → no restriction
        filters = IndexFilters(access_control_list=[], project_id=789)
        result = build_vespa_filters(filters)
        assert f"!({HIDDEN}=true) and " == result

        # project_id with document_set → both OR'd
        filters = IndexFilters(
            access_control_list=[], project_id=789, document_set=["set1"]
        )
        result = build_vespa_filters(filters)
        assert (
            f'!({HIDDEN}=true) and (({DOCUMENT_SETS} contains "set1") or ({USER_PROJECT} contains "789")) and '
            == result
        )

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
        """Test combining multiple filter types.

        Knowledge-scope filters (document_set, project_id, persona_id)
        are OR'd together, while all other filters are AND'd.
        """
        filters = IndexFilters(
            access_control_list=["user1", "group1"],
            source_type=[DocumentSource.WEB],
            tags=[Tag(tag_key="color", tag_value="red")],
            document_set=["set1"],
            project_id=789,
            persona_id=42,
            time_cutoff=datetime(2023, 1, 1, tzinfo=timezone.utc),
        )

        result = build_vespa_filters(filters)

        expected = f"!({HIDDEN}=true) and "
        expected += 'weightedSet(access_control_list, {"user1":1, "group1":1}) and '
        expected += f'({SOURCE_TYPE} contains "web") and '
        expected += f'({METADATA_LIST} contains "color{INDEX_SEPARATOR}red") and '
        # Knowledge scope filters are OR'd together
        # (persona_id is primary, project_id is additive — order reflects this)
        expected += (
            f'(({DOCUMENT_SETS} contains "set1")'
            f' or ({PERSONAS} contains "42")'
            f' or ({USER_PROJECT} contains "789")'
            f") and "
        )
        cutoff_secs = int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())
        expected += f"!({DOC_UPDATED_AT} < {cutoff_secs}) and "

        assert expected == result

        # With trailing AND removed
        result_no_trailing = build_vespa_filters(filters, remove_trailing_and=True)
        assert expected[:-5] == result_no_trailing  # Remove trailing " and "

    def test_knowledge_scope_single_filter_not_wrapped(self) -> None:
        """When only one knowledge-scope filter is present it should not
        be wrapped in an extra OR group."""
        filters = IndexFilters(access_control_list=[], document_set=["set1"])
        result = build_vespa_filters(filters)
        assert f'!({HIDDEN}=true) and ({DOCUMENT_SETS} contains "set1") and ' == result

    def test_persona_id_is_primary_knowledge_scope(self) -> None:
        """persona_id alone should trigger a knowledge scope restriction
        (a persona with user files IS explicit knowledge)."""
        filters = IndexFilters(access_control_list=[], persona_id=42)
        result = build_vespa_filters(filters)
        assert f'!({HIDDEN}=true) and ({PERSONAS} contains "42") and ' == result

    def test_persona_id_with_project_id(self) -> None:
        """When persona_id triggers the scope, project_id should be
        OR'd in additively."""
        filters = IndexFilters(access_control_list=[], persona_id=42, project_id=789)
        result = build_vespa_filters(filters)
        expected = (
            f"!({HIDDEN}=true) and "
            f'(({PERSONAS} contains "42") or ({USER_PROJECT} contains "789")) and '
        )
        assert expected == result

    def test_knowledge_scope_document_set_and_persona_ored(self) -> None:
        """Document set filter and persona_id must be OR'd so that
        connector documents (in the set) and persona user files can
        both be found."""
        filters = IndexFilters(
            access_control_list=[],
            document_set=["engineering"],
            persona_id=42,
        )
        result = build_vespa_filters(filters)
        expected = f'!({HIDDEN}=true) and (({DOCUMENT_SETS} contains "engineering") or ({PERSONAS} contains "42")) and '
        assert expected == result

    def test_acl_large_list_uses_weighted_set(self) -> None:
        """Verify that large ACL lists produce a weightedSet clause
        instead of OR-chained contains — this is what prevents Vespa
        HTTP 400 errors for users with thousands of permission groups."""
        acl = [f"external_group:google_drive_{i}" for i in range(10_000)]
        acl += ["user_email:user@example.com", "__PUBLIC__"]
        filters = IndexFilters(access_control_list=acl)
        result = build_vespa_filters(filters)

        assert "weightedSet(access_control_list, {" in result
        # Must NOT contain OR-chained contains clauses
        assert "access_control_list contains" not in result
        # All entries should be present
        assert '"external_group:google_drive_0":1' in result
        assert '"external_group:google_drive_9999":1' in result
        assert '"user_email:user@example.com":1' in result
        assert '"__PUBLIC__":1' in result

    def test_acl_empty_strings_filtered(self) -> None:
        """Empty strings in the ACL list should be filtered out."""
        filters = IndexFilters(access_control_list=["user1", "", "group1"])
        result = build_vespa_filters(filters)
        assert (
            result
            == f'!({HIDDEN}=true) and weightedSet(access_control_list, {{"user1":1, "group1":1}}) and '
        )

        # All empty
        filters = IndexFilters(access_control_list=["", ""])
        result = build_vespa_filters(filters)
        assert result == f"!({HIDDEN}=true) and "

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
