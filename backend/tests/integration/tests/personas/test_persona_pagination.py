import requests

from tests.integration.common_utils.constants import API_SERVER_URL
from tests.integration.common_utils.managers.persona import PersonaManager
from tests.integration.common_utils.test_models import DATestUser


def _list_personas_paginated(
    user: DATestUser,
    page_num: int,
    page_size: int,
    include_deleted: bool = False,
    get_editable: bool = False,
) -> dict:
    """Fetches a paginated page of personas."""
    response = requests.get(
        f"{API_SERVER_URL}/persona/paginated",
        params={
            "page_num": page_num,
            "page_size": page_size,
            "include_deleted": include_deleted,
            "get_editable": get_editable,
        },
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return response.json()


def _list_personas_admin_paginated(
    user: DATestUser,
    page_num: int,
    page_size: int,
    include_deleted: bool = False,
    get_editable: bool = False,
) -> dict:
    """Fetches a paginated page of personas (admin endpoint)."""
    response = requests.get(
        f"{API_SERVER_URL}/admin/persona/paginated",
        params={
            "page_num": page_num,
            "page_size": page_size,
            "include_deleted": include_deleted,
            "get_editable": get_editable,
        },
        headers=user.headers,
        cookies=user.cookies,
    )
    response.raise_for_status()
    return response.json()


def test_persona_pagination_basic(reset: None, admin_user: DATestUser) -> None:
    """Test basic pagination - verify correct items and total count."""
    # Preconditions
    personas_to_create = 25
    personas = []
    for i in range(personas_to_create):
        persona = PersonaManager.create(
            name=f"Test Persona {i}",
            user_performing_action=admin_user,
        )
        personas.append(persona)

    # Under test and postconditions
    # Test page 0 with size 10.
    page_0 = _list_personas_paginated(admin_user, page_num=0, page_size=10)
    assert "items" in page_0
    assert "total_items" in page_0
    assert len(page_0["items"]) == 10
    assert (
        page_0["total_items"] >= personas_to_create
    )  # At least personas_to_create (may have default personas)

    # Test page 2 with size 10 (should have 5+ items if only our test personas
    # exist).
    page_2 = _list_personas_paginated(admin_user, page_num=2, page_size=10)
    assert len(page_2["items"]) >= 5
    assert page_2["total_items"] >= personas_to_create

    # Test page beyond end (page 10 with size 10, offset 100).
    page_beyond = _list_personas_paginated(admin_user, page_num=10, page_size=10)
    assert len(page_beyond["items"]) == 0
    assert page_beyond["total_items"] >= personas_to_create  # Total doesn't change.


def test_persona_pagination_ordering(reset: None, admin_user: DATestUser) -> None:
    """Test ordering - display_priority ASC nulls last, then ID ASC."""
    # Preconditions
    # Create personas with specific display_priority values.
    # NOTE: We can't easily set display_priority via PersonaManager.create,
    # so we'll verify the ordering of personas we create from id.
    persona_a = PersonaManager.create(
        name="Persona A",
        description="Priority will be null",
        user_performing_action=admin_user,
    )
    persona_b = PersonaManager.create(
        name="Persona B",
        description="Priority will be null",
        user_performing_action=admin_user,
    )
    persona_c = PersonaManager.create(
        name="Persona C",
        description="Priority will be null",
        user_performing_action=admin_user,
    )

    # Under test
    page_0 = _list_personas_paginated(admin_user, page_num=0, page_size=100)

    # Postconditions
    # Find our personas in the results.
    our_persona_ids = {persona_a.id, persona_b.id, persona_c.id}
    our_personas_in_results = [p for p in page_0["items"] if p["id"] in our_persona_ids]
    # Verify they appear in ID ascending order (since all have null priority).
    assert len(our_personas_in_results) == 3
    ids_in_order = [p["id"] for p in our_personas_in_results]
    assert ids_in_order == sorted(
        ids_in_order
    ), "Personas should be sorted by ID when priority is null."


def test_persona_pagination_admin_endpoint(reset: None, admin_user: DATestUser) -> None:
    """Test admin paginated endpoint returns PersonaSnapshot format."""
    # Preconditions
    personas_to_create = 5
    for i in range(personas_to_create):
        PersonaManager.create(
            name=f"Admin Test Persona {i}",
            user_performing_action=admin_user,
        )

    # Under test
    page_0 = _list_personas_admin_paginated(admin_user, page_num=0, page_size=10)

    # Postconditions
    assert "items" in page_0
    assert "total_items" in page_0
    assert len(page_0["items"]) >= personas_to_create
    assert page_0["total_items"] >= personas_to_create
    # Verify admin-specific fields are present (PersonaSnapshot has more
    # fields).
    first_persona = page_0["items"][0]
    # PersonaSnapshot should have these fields that MinimalPersonaSnapshot
    # doesn't.
    assert "users" in first_persona
    assert "groups" in first_persona
    assert "user_file_ids" in first_persona


def test_persona_pagination_with_deleted(reset: None, admin_user: DATestUser) -> None:
    """Test pagination with include_deleted parameter."""
    # Preconditions
    # Create and delete a persona.
    persona = PersonaManager.create(
        name="To Be Deleted",
        user_performing_action=admin_user,
    )
    PersonaManager.delete(persona, user_performing_action=admin_user)

    # Under test and postconditions
    # Without include_deleted, should not appear.
    page_without_deleted = _list_personas_paginated(
        admin_user, page_num=0, page_size=100, include_deleted=False
    )
    persona_ids_without_deleted = [p["id"] for p in page_without_deleted["items"]]
    assert persona.id not in persona_ids_without_deleted

    # With include_deleted, should appear.
    page_with_deleted = _list_personas_paginated(
        admin_user, page_num=0, page_size=100, include_deleted=True
    )
    persona_ids_with_deleted = [p["id"] for p in page_with_deleted["items"]]
    assert persona.id in persona_ids_with_deleted

    # Total counts should differ.
    assert page_with_deleted["total_items"] > page_without_deleted["total_items"]


def test_persona_pagination_page_size_limits(
    reset: None, admin_user: DATestUser
) -> None:
    """Test page_size parameter validation (max 1000)."""
    # Preconditions
    # Create a few personas.
    for i in range(5):
        PersonaManager.create(
            name=f"Size Limit Test {i}",
            user_performing_action=admin_user,
        )

    # Under test and postconditions
    # Valid page_size of 1
    response = requests.get(
        f"{API_SERVER_URL}/persona/paginated",
        params={"page_num": 0, "page_size": 1},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    data = response.json()
    assert len(data["items"]) <= 1

    # Valid page_size of 1000
    response = requests.get(
        f"{API_SERVER_URL}/persona/paginated",
        params={"page_num": 0, "page_size": 1000},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 200
    data = response.json()
    # We assume not that many default personas are made.
    assert len(data["items"]) == data["total_items"]

    # Invalid page_size of 1001 (exceeds max)
    response = requests.get(
        f"{API_SERVER_URL}/persona/paginated",
        params={"page_num": 0, "page_size": 1001},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 422  # Validation error

    # Invalid page_size of 0
    response = requests.get(
        f"{API_SERVER_URL}/persona/paginated",
        params={"page_num": 0, "page_size": 0},
        headers=admin_user.headers,
        cookies=admin_user.cookies,
    )
    assert response.status_code == 422  # Validation error


def test_persona_pagination_count_accuracy(reset: None, admin_user: DATestUser) -> None:
    """Test that total_items count is consistent across pages."""
    # Preconditions
    # Create 15 personas.
    created_personas = []
    for i in range(15):
        persona = PersonaManager.create(
            name=f"Count Test {i}",
            user_performing_action=admin_user,
        )
        created_personas.append(persona)

    # Under test and postconditions
    # Fetch first page to get total count.
    page_0 = _list_personas_paginated(admin_user, page_num=0, page_size=5)
    total_items = page_0["total_items"]
    assert total_items >= 15

    # Fetch all pages to cover all personas.
    all_ids_from_pages: set[int] = set()
    num_pages_needed = (total_items + 4) // 5  # Ceiling division
    for page_num in range(num_pages_needed):
        page = _list_personas_paginated(admin_user, page_num=page_num, page_size=5)
        # All pages should report the same total.
        assert (
            page["total_items"] == total_items
        ), f"Page {page_num} has inconsistent total_items"
        all_ids_from_pages.update(p["id"] for p in page["items"])

    # Our created personas should all appear.
    our_ids = {p.id for p in created_personas}
    assert our_ids.issubset(
        all_ids_from_pages
    ), "All created personas should appear in paginated results"


def test_persona_pagination_user_permissions(
    reset: None, admin_user: DATestUser, basic_user: DATestUser
) -> None:
    """Test that pagination respects user permissions."""
    # Preconditions
    # Admin creates a private persona (not shared).
    private_persona = PersonaManager.create(
        name="Private Persona",
        description="Not shared",
        is_public=False,
        user_performing_action=admin_user,
    )
    # Admin creates a public persona.
    public_persona = PersonaManager.create(
        name="Public Persona",
        description="Shared with all",
        is_public=True,
        user_performing_action=admin_user,
    )

    # Under test and postconditions
    # Admin should see both in paginated results.
    admin_page = _list_personas_paginated(admin_user, page_num=0, page_size=100)
    admin_ids = {p["id"] for p in admin_page["items"]}
    assert private_persona.id in admin_ids
    assert public_persona.id in admin_ids

    # Basic user should only see public persona.
    user_page = _list_personas_paginated(basic_user, page_num=0, page_size=100)
    user_ids = {p["id"] for p in user_page["items"]}
    assert private_persona.id not in user_ids
    assert public_persona.id in user_ids

    # Totals should differ.
    assert admin_page["total_items"] > user_page["total_items"]
