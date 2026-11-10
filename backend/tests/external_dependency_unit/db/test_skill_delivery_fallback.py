"""Delivery tries eligible duplicate names until one complete bundle can load."""

import io
import zipfile
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock

import pytest
from sqlalchemy.orm import Session

from onyx.configs.constants import FileOrigin
from onyx.db import skill as skill_db
from onyx.db.enums import SkillInstallationPolicy as Policy
from onyx.db.file_record import FileRecordNotFoundError
from onyx.db.models import Skill
from onyx.db.skill import SkillValidityUpdate, skill_user_states
from onyx.file_store.file_store import FileStore, get_default_file_store
from onyx.skills import push
from tests.external_dependency_unit.craft.db_helpers import (
    make_skill,
    make_user,
    share_skill_with_user,
)

pytestmark = pytest.mark.usefixtures("tenant_context")


def _bundle(skill: Skill) -> bytes:
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as bundle:
        bundle.writestr(
            "SKILL.md", f"---\nname: {skill.name}\ndescription: Test\n---\n{skill.id}"
        )
        bundle.writestr(f"{skill.id}.txt", "Only the delivered skill")
    return output.getvalue()


@pytest.mark.parametrize("validity", [True, None])
@pytest.mark.parametrize("failure", ["timeout", "missing", "corrupt"])
@pytest.mark.parametrize("payload", [False, True])
def test_delivery_uses_own_after_company_bundle_failure(
    db_session: Session,
    monkeypatch: pytest.MonkeyPatch,
    validity: bool | None,
    failure: str,
    payload: bool,
) -> None:
    user = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    company = make_skill(db_session, is_public=True)
    own = make_skill(db_session, name=company.name, author_user_id=user.id)
    shared = make_skill(db_session, name=company.name, author_user_id=other.id)
    share_skill_with_user(db_session, shared, user)
    for skill in (company, own, shared):
        skill.installation_policy = Policy.DEFAULT
        assert skill.current_version is not None
        skill.current_version.is_valid = True
    assert company.current_version is not None
    assert own.current_version is not None
    company_version = company.current_version
    own_version = own.current_version
    company_version.is_valid = validity
    db_session.flush()
    # Reads have no storage knowledge; they still identify the company candidate.
    state = skill_user_states(user, [own.id], db_session)[own.id]
    assert state.hidden_by_skill_id == company.id

    def read(file_id: str, **_kwargs: object) -> io.BytesIO:
        if file_id == company_version.bundle_file_id:
            if failure == "timeout":
                raise TimeoutError("temporary outage")
            if failure == "missing":
                raise FileRecordNotFoundError("missing bundle")
            return io.BytesIO(b"not a zip")
        assert file_id == own_version.bundle_file_id, "read a losing bundle"
        return io.BytesIO(_bundle(own))

    store = MagicMock(spec=FileStore)
    store.read_file.side_effect = read
    persist = MagicMock()
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)
    monkeypatch.setattr(push, "persist_skill_validity", persist)
    if payload:
        _, files = push.build_user_skills_payload(user, db_session)
    else:
        files = push.build_skills_fileset_for_user(user, db_session)
    assert {p: b for p, b in files.items() if p.startswith(own.name + "/")} == {
        f"{own.name}/SKILL.md": (
            f"---\nname: {own.name}\ndescription: Test\n---\n{own.id}".encode()
        ),
        f"{own.name}/{own.id}.txt": b"Only the delivered skill",
    }
    assert [call.args[0] for call in store.read_file.call_args_list] == [
        company_version.bundle_file_id,
        own_version.bundle_file_id,
    ]
    expected_updates = (
        [
            SkillValidityUpdate(
                skill_id=company.id,
                version_id=company_version.id,
                bundle_file_id=company_version.bundle_file_id,
                is_valid=False,
            )
        ]
        if validity is None and failure in {"corrupt", "missing"}
        else []
    )
    persist.assert_called_once_with(expected_updates)


def test_delivery_orders_all_candidates_and_stops_after_success(
    db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    user = make_user(db_session, standard_account=True)
    other = make_user(db_session, standard_account=True)
    company = make_skill(db_session, is_public=True)
    own = make_skill(db_session, name=company.name, author_user_id=user.id)
    shared = [
        make_skill(db_session, name=company.name, author_user_id=other.id)
        for _ in range(3)
    ]
    for skill in shared:
        share_skill_with_user(db_session, skill, user)
    shared.sort(key=lambda skill: skill.id)
    order = [company, own, *shared]
    for index, skill in enumerate(order):
        skill.installation_policy = Policy.DEFAULT
        assert skill.current_version is not None
        skill.current_version.is_valid = True
        # Company/own priority beats age; shared ties use UUID before later rows.
        skill.created_at = datetime(2020, 1, 1, tzinfo=timezone.utc)
        if index < 2:
            skill.created_at += timedelta(days=2 - index)
    shared[-1].created_at += timedelta(days=1)
    db_session.flush()
    bundles = {
        skill.current_version.bundle_file_id: skill
        for skill in order
        if skill.current_version is not None
    }
    winner = shared[1]

    def read(file_id: str, **_kwargs: object) -> io.BytesIO:
        skill = bundles[file_id]
        if skill.id == winner.id:
            return io.BytesIO(_bundle(skill))
        assert skill.id != shared[-1].id, "read after a winner assembled"
        raise TimeoutError("temporary outage")

    store = MagicMock(spec=FileStore)
    store.read_file.side_effect = read
    monkeypatch.setattr(push, "get_default_file_store", lambda: store)
    monkeypatch.setattr(push, "persist_skill_validity", MagicMock())
    resolve = MagicMock(wraps=skill_db._runtime_name_winners)
    monkeypatch.setattr(skill_db, "_runtime_name_winners", resolve)
    files = push.build_skills_fileset_for_user(user, db_session)
    resolve.assert_called_once()
    assert resolve.call_args.args == (user, db_session)
    assert files[f"{winner.name}/{winner.id}.txt"] == b"Only the delivered skill"
    assert [call.args[0] for call in store.read_file.call_args_list] == [
        skill.current_version.bundle_file_id
        for skill in order[:-1]
        if skill.current_version is not None
    ]


def test_lazy_invalidity_updates_library_winner_after_delivery(
    db_session: Session,
) -> None:
    user = make_user(db_session, standard_account=True)
    company = make_skill(db_session, is_public=True)
    own = make_skill(db_session, name=company.name, author_user_id=user.id)
    store = get_default_file_store()
    file_ids: list[str] = []
    try:
        for skill, content in ((company, b"corrupt"), (own, _bundle(own))):
            file_id = store.save_file(
                content=io.BytesIO(content),
                display_name="delivery-test.zip",
                file_origin=FileOrigin.SKILL_BUNDLE,
                file_type="application/zip",
            )
            file_ids.append(file_id)
            skill.installation_policy = Policy.DEFAULT
            assert skill.current_version is not None
            skill.current_version.bundle_file_id = file_id
            skill.current_version.is_valid = None
        db_session.commit()
        state = skill_user_states(user, [own.id], db_session)[own.id]
        assert state.hidden_by_skill_id == company.id
        files = push.build_skills_fileset_for_user(user, db_session)
        assert files[f"{own.name}/{own.id}.txt"] == b"Only the delivered skill"
        db_session.expire_all()
        assert company.current_version is not None
        assert company.current_version.is_valid is False
        state = skill_user_states(user, [own.id], db_session)[own.id]
        assert state.enabled
        assert state.hidden_by_skill_id is None
    finally:
        db_session.rollback()
        db_session.delete(company)
        db_session.delete(own)
        db_session.commit()
        for file_id in file_ids:
            store.delete_file(file_id, error_on_missing=False)
