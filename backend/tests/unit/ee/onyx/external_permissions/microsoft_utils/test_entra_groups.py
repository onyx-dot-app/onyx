"""Entra group expansion and enumeration shared by the Microsoft perm-sync paths."""

from unittest.mock import MagicMock, patch

from ee.onyx.external_permissions.microsoft_utils.entra_groups import (
    ResolvedEntraGroup,
    enumerate_entra_groups,
    expand_entra_group,
    list_nested_entra_groups,
    normalize_email,
    resolve_entra_group_name,
)
from onyx.connectors.microsoft_utils.entra import EntraDirectoryObject, EntraGroup
from onyx.connectors.microsoft_utils.models import (
    EntraMember,
    EntraMemberKind,
)
from tests.unit.onyx.connectors.microsoft_utils.fake_sharepoint_reader import (
    FakeSharepointReader,
)

MODULE = "ee.onyx.external_permissions.microsoft_utils.entra_groups"
PRINCIPALS = "onyx.connectors.microsoft_utils.sharepoint_principals"
GROUP_ID = "11111111-1111-1111-1111-111111111111"
NESTED_GROUP_ID = "22222222-2222-2222-2222-222222222222"


def test_normalize_email_strips_onmicrosoft() -> None:
    assert normalize_email("user@contoso.onmicrosoft.com") == "user@contoso.com"


def test_normalize_email_noop_for_normal_domain() -> None:
    assert normalize_email("user@contoso.com") == "user@contoso.com"


@patch(f"{PRINCIPALS}.find_group_id_by_name", return_value=None)
def test_unresolved_group_keeps_the_none_suffix(_mock_find: MagicMock) -> None:
    """Persisted ACLs were written with this name, so it must not change."""
    name = resolve_entra_group_name(MagicMock(), "Engineering", "Engineering")

    assert name == "Engineering_None"


def test_failed_name_lookup_resolves_to_none() -> None:
    reader = MagicMock()
    reader.find_entra_group_id.side_effect = RuntimeError("Graph is down")

    assert resolve_entra_group_name(reader, "Engineering", "Engineering") == (
        "Engineering_None"
    )


def _directory_object(object_id: str, **fields: str) -> EntraDirectoryObject:
    return EntraDirectoryObject.model_validate({"id": object_id, **fields})


def test_enumerate_yields_groups_with_normalized_members() -> None:
    reader = FakeSharepointReader(
        entra_groups=[
            EntraGroup(id="g1", displayName="Engineering"),
            EntraGroup(id="g2", displayName="Marketing"),
        ],
        entra_group_member_objects={
            "g1": [_directory_object("u1", userPrincipalName="alice@contoso.com")],
            "g2": [_directory_object("u2", mail="bob@contoso.onmicrosoft.com")],
        },
    )

    results = list(enumerate_entra_groups(reader, already_resolved=set()))

    assert len(results) == 2
    eng = next(r for r in results if r.id == "Engineering_g1")
    assert eng.user_emails == ["alice@contoso.com"]
    mkt = next(r for r in results if r.id == "Marketing_g2")
    assert mkt.user_emails == ["bob@contoso.com"]


def test_enumerate_skips_already_resolved() -> None:
    reader = FakeSharepointReader(
        entra_groups=[EntraGroup(id="g1", displayName="Engineering")]
    )

    results = list(enumerate_entra_groups(reader, already_resolved={"Engineering_g1"}))

    assert results == []


def test_enumerate_stops_at_threshold() -> None:
    reader = FakeSharepointReader(
        entra_groups=[EntraGroup(id=f"g{i}", displayName=f"Group{i}") for i in range(5)]
    )

    results = list(enumerate_entra_groups(reader, already_resolved=set(), threshold=3))

    assert [r.id for r in results] == ["Group0_g0", "Group1_g1", "Group2_g2"]


def test_expand_collects_member_emails() -> None:
    reader = FakeSharepointReader(
        entra_members={
            GROUP_ID: [
                EntraMember(
                    kind=EntraMemberKind.USER,
                    id="u1",
                    user_principal_name="member@contoso.onmicrosoft.com",
                ),
                EntraMember(kind=EntraMemberKind.USER, id="u2", mail="bob@contoso.com"),
                EntraMember(kind=EntraMemberKind.UNKNOWN, id="d1"),
            ]
        }
    )

    groups, user_emails = expand_entra_group(reader, GROUP_ID)

    assert groups == set()
    assert user_emails == {"member@contoso.com", "bob@contoso.com"}


def test_expand_names_nested_groups_for_onyx() -> None:
    reader = FakeSharepointReader(
        entra_members={
            GROUP_ID: [
                EntraMember(
                    kind=EntraMemberKind.GROUP,
                    id=NESTED_GROUP_ID,
                    display_name="Nested",
                ),
                EntraMember(kind=EntraMemberKind.GROUP, id="nameless"),
            ]
        }
    )

    groups, user_emails = expand_entra_group(reader, GROUP_ID)

    assert groups == {
        ResolvedEntraGroup(
            id=NESTED_GROUP_ID,
            name=f"Nested_{NESTED_GROUP_ID}",
        )
    }
    assert user_emails == set()


def test_expand_by_display_name_looks_the_group_up() -> None:
    reader = FakeSharepointReader(entra_group_ids={"Engineering": GROUP_ID})

    expand_entra_group(reader, "Engineering")

    assert reader.operations() == ["find_entra_group_id", "list_entra_group_members"]


def test_nested_groups_are_named_for_onyx() -> None:
    reader = FakeSharepointReader(
        nested_entra_groups={
            GROUP_ID: [EntraGroup(id=NESTED_GROUP_ID, displayName="Platform")]
        }
    )

    groups = list_nested_entra_groups(reader, GROUP_ID)

    assert groups == {
        ResolvedEntraGroup(id=NESTED_GROUP_ID, name=f"Platform_{NESTED_GROUP_ID}")
    }
    assert "list_entra_group_members" not in reader.operations()
