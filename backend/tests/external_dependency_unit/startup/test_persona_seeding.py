"""
Test suite for the persona seeding functionality.

Tests that load_builtin_personas creates expected personas on initial call
and is idempotent on subsequent calls.
"""

import pytest
from sqlalchemy.inspection import inspect
from sqlalchemy.orm import Session

from onyx.db.models import Persona
from onyx.db.persona import get_personas
from onyx.seeding.load_yamls import load_builtin_personas
from onyx.seeding.prebuilt_personas import get_prebuilt_personas
from onyx.seeding.prebuilt_personas import PrebuiltPersona
from onyx.tools.built_in_tools import load_builtin_tools


def _get_comparable_persona_fields() -> list[str]:
    """Get all comparable fields from Persona model, excluding relationships and non-comparable fields."""
    # Get all column names from the Persona model
    inspector = inspect(Persona)
    column_names = [column.key for column in inspector.columns]

    # Fields to exclude from comparison (relationships, auto-generated, etc.)
    excluded_fields = {
        "user_id",  # Will be None for builtin personas
        "deleted",  # Will be False for builtin personas
        "search_start_date",  # Will be None for builtin personas
        "uploaded_image_id",  # Will be None for builtin personas
        # Note: we handle 'id' specially since it's negated
    }

    # Return fields that can be meaningfully compared
    return [field for field in column_names if field not in excluded_fields]


def _compare_persona_attributes(
    created_persona: Persona,
    expected_persona: PrebuiltPersona,
    comparable_fields: list[str],
) -> None:
    """Compare all fields between created and expected persona."""
    for field in comparable_fields:
        if field == "id":
            # Special handling for ID field (gets negated)
            if expected_persona.id is not None:
                expected_value = -1 * expected_persona.id
                actual_value = getattr(created_persona, field)
                assert actual_value == expected_value, (
                    f"Field '{field}': expected {expected_value}, got {actual_value} "
                    f"for persona '{created_persona.name}'"
                )
        elif field in ["builtin_persona", "is_public"]:
            # These are always set to True by load_builtin_personas
            actual_value = getattr(created_persona, field)
            if field == "builtin_persona":
                assert (
                    actual_value is True
                ), f"builtin_persona should be True for '{created_persona.name}'"
            elif field == "is_public":
                assert (
                    actual_value is True
                ), f"is_public should be True for '{created_persona.name}'"
        else:
            # Compare field values directly
            expected_value = getattr(expected_persona, field)
            actual_value = getattr(created_persona, field)
            assert actual_value == expected_value, (
                f"Field '{field}': expected {expected_value}, got {actual_value} "
                f"for persona '{created_persona.name}'"
            )


def _validate_all_personas(
    all_personas: list[Persona],
    expected_personas: list[PrebuiltPersona],
) -> None:
    """Validate all personas exist with correct attributes."""
    comparable_fields = _get_comparable_persona_fields()

    for expected_persona in expected_personas:
        if expected_persona.id is not None:
            expected_db_id = -1 * expected_persona.id

            # Find persona by DB ID (more reliable than name for personas with explicit IDs)
            created_persona = next(
                (p for p in all_personas if p.id == expected_db_id), None
            )
            assert (
                created_persona is not None
            ), f"Persona '{expected_persona.name}' with ID {expected_db_id} was not found"

            # Programmatically compare all fields
            _compare_persona_attributes(
                created_persona, expected_persona, comparable_fields
            )

            # Verify starter messages (special case since it's a list)
            if expected_persona.starter_messages:
                assert created_persona.starter_messages is not None
                assert len(created_persona.starter_messages) == len(
                    expected_persona.starter_messages
                )
                for i, expected_msg in enumerate(expected_persona.starter_messages):
                    created_msg = created_persona.starter_messages[i]
                    assert created_msg.name == expected_msg.name
                    assert created_msg.message == expected_msg.message
            else:
                assert created_persona.starter_messages == []


def test_load_builtin_personas_creates_expected_personas(db_session: Session) -> None:
    """Test that load_builtin_personas ensures expected personas with IDs
    exist with correct attributes.
    """
    # Tools must exist before loading builtin personas
    load_builtin_tools(db_session)

    # Get existing state before load
    all_personas_before = get_personas(db_session)
    assert (
        len(all_personas_before) == 1
    ), "Only dummy persona from b156fa702355_chat_reworked.py should exist"
    assert all_personas_before[0].name == ""

    # Call load_builtin_personas
    load_builtin_personas(db_session)

    # Get state after load attempt
    builtin_personas_after = [p for p in get_personas(db_session) if p.builtin_persona]

    # If load succeeded, verify all personas exist
    # Get expected personas from the prebuilt personas configuration
    expected_personas = get_prebuilt_personas()
    expected_persona_names = {p.name for p in expected_personas}
    builtin_persona_names = {p.name for p in builtin_personas_after}
    missing_personas = expected_persona_names - builtin_persona_names
    assert not missing_personas, f"Missing expected personas: {missing_personas}"

    # Verify personas with IDs have correct attributes (these should always work)
    _validate_all_personas(builtin_personas_after, expected_personas)

    # load again, verify idempotency
    load_builtin_personas(db_session)
    builtin_personas_after_second_load = [
        p for p in get_personas(db_session) if p.builtin_persona
    ]
    _validate_all_personas(builtin_personas_after_second_load, expected_personas)


if __name__ == "__main__":
    # Run with: python -m pytest tests/external_dependency_unit/startup/test_persona_seeding.py -v
    pytest.main([__file__, "-v"])
