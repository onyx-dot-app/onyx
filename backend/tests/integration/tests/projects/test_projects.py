from typing import List

import pytest

from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.models import UserFile
from onyx.server.features.projects.models import UserProjectSnapshot
from tests.integration.common_utils.managers.project import ProjectManager
from tests.integration.common_utils.reset import reset_all
from tests.integration.common_utils.test_models import DATestLLMProvider
from tests.integration.common_utils.test_models import DATestUser


@pytest.fixture(scope="module", autouse=True)
def reset_for_module() -> None:
    """Reset all data once before running any tests in this module."""
    reset_all()


def test_projects_flow(
    reset_for_module: None,
    basic_user: DATestUser,
    llm_provider: DATestLLMProvider,
) -> None:
    """End-to-end project flow covering creation, listing, files, instructions, deletion, and edge cases."""
    # Case 1: Project creation and listing
    ProjectManager.create(
        name="Test Project 1",
        user_performing_action=basic_user,
    )
    ProjectManager.create(
        name="Test Project 2",
        user_performing_action=basic_user,
    )

    projects = ProjectManager.get_all(user_performing_action=basic_user)
    assert len(projects) >= 2
    project_names = {p.name for p in projects}
    assert "Test Project 1" in project_names
    assert "Test Project 2" in project_names
    assert all(str(p.user_id) == basic_user.id for p in projects)

    # Case 2: File upload and management
    file_project = ProjectManager.create(
        name="File Test Project",
        user_performing_action=basic_user,
    )
    test_files = [
        ("test1.txt", b"This is test file 1 content"),
        ("test2.txt", b"This is test file 2 content"),
    ]
    upload_result = ProjectManager.upload_files(
        project_id=file_project.id,
        files=test_files,
        user_performing_action=basic_user,
    )
    assert len(upload_result.user_files) == 2
    assert len(upload_result.non_accepted_files) == 0
    assert len(upload_result.unsupported_files) == 0
    project_files = ProjectManager.get_project_files(
        project_id=file_project.id,
        user_performing_action=basic_user,
    )
    assert len(project_files) == 2
    file_names = {f.name for f in project_files}
    assert "test1.txt" in file_names
    assert "test2.txt" in file_names

    # Case 3: Instructions set and update
    instructions_project = ProjectManager.create(
        name="Instructions Test Project",
        user_performing_action=basic_user,
    )
    instructions = "These are test project instructions"
    result = ProjectManager.set_instructions(
        project_id=instructions_project.id,
        instructions=instructions,
        user_performing_action=basic_user,
    )
    assert result == instructions
    new_instructions = "These are updated test project instructions"
    result = ProjectManager.set_instructions(
        project_id=instructions_project.id,
        instructions=new_instructions,
        user_performing_action=basic_user,
    )
    assert result == new_instructions

    # Case 4: Deletion with files (unlink but do not delete files)
    delete_file_project = ProjectManager.create(
        name="Deletion Test Project",
        user_performing_action=basic_user,
    )
    del_test_files = [
        ("delete_test1.txt", b"This is test file 1 content"),
        ("delete_test2.txt", b"This is test file 2 content"),
    ]
    ProjectManager.upload_files(
        project_id=delete_file_project.id,
        files=del_test_files,
        user_performing_action=basic_user,
    )
    del_project_files = ProjectManager.get_project_files(
        project_id=delete_file_project.id,
        user_performing_action=basic_user,
    )
    assert len(del_project_files) == 2
    deletion_success = ProjectManager.delete(
        project_id=delete_file_project.id,
        user_performing_action=basic_user,
    )
    assert deletion_success
    assert ProjectManager.verify_deleted(
        project_id=delete_file_project.id,
        user_performing_action=basic_user,
    )
    assert ProjectManager.verify_files_unlinked(
        project_id=delete_file_project.id,
        user_performing_action=basic_user,
    )
    with get_session_with_current_tenant() as db_session:
        file_ids = [f.id for f in del_project_files]
        remaining_files = (
            db_session.query(UserFile).filter(UserFile.id.in_(file_ids)).all()
        )
        assert len(remaining_files) == 2

    # Case 5: Deletion with chat sessions unlinked
    chat_project = ProjectManager.create(
        name="Chat Session Test Project",
        user_performing_action=basic_user,
    )
    deletion_success = ProjectManager.delete(
        project_id=chat_project.id,
        user_performing_action=basic_user,
    )
    assert deletion_success
    assert ProjectManager.verify_chat_sessions_unlinked(
        project_id=chat_project.id,
        user_performing_action=basic_user,
    )

    # Case 6: Multiple project operations
    projects_group: List[UserProjectSnapshot] = []
    for i in range(3):
        proj = ProjectManager.create(
            name=f"Multi-op Project {i}",
            user_performing_action=basic_user,
        )
        projects_group.append(proj)

    for i, proj in enumerate(projects_group):
        tfiles = [
            (f"multi_test{i}_1.txt", b"This is test file 1 content"),
            (f"multi_test{i}_2.txt", b"This is test file 2 content"),
        ]
        ProjectManager.upload_files(
            project_id=proj.id,
            files=tfiles,
            user_performing_action=basic_user,
        )

    for i, proj in enumerate(projects_group):
        instr = f"Instructions for project {i}"
        res = ProjectManager.set_instructions(
            project_id=proj.id,
            instructions=instr,
            user_performing_action=basic_user,
        )
        assert res == instr

    for proj in projects_group:
        proj_files = ProjectManager.get_project_files(
            project_id=proj.id,
            user_performing_action=basic_user,
        )
        assert len(proj_files) == 2
        deletion_success = ProjectManager.delete(
            project_id=proj.id,
            user_performing_action=basic_user,
        )
        assert deletion_success
        assert ProjectManager.verify_deleted(
            project_id=proj.id,
            user_performing_action=basic_user,
        )
        assert ProjectManager.verify_files_unlinked(
            project_id=proj.id,
            user_performing_action=basic_user,
        )
        with get_session_with_current_tenant() as db_session:
            file_ids = [f.id for f in proj_files]
            remaining_files = (
                db_session.query(UserFile).filter(UserFile.id.in_(file_ids)).all()
            )
            assert len(remaining_files) == 2

    # Case 7: Edge cases
    with pytest.raises(Exception):
        ProjectManager.create(
            name="",
            user_performing_action=basic_user,
        )

    non_existent_id = 99999
    deletion_success = ProjectManager.delete(
        project_id=non_existent_id,
        user_performing_action=basic_user,
    )
    assert not deletion_success

    with pytest.raises(Exception):
        ProjectManager.set_instructions(
            project_id=non_existent_id,
            instructions="Test instructions",
            user_performing_action=basic_user,
        )

    with pytest.raises(Exception):
        ProjectManager.upload_files(
            project_id=non_existent_id,
            files=[("test.txt", b"content")],
            user_performing_action=basic_user,
        )

    long_name = "a" * 1000
    with pytest.raises(Exception):
        ProjectManager.create(
            name=long_name,
            user_performing_action=basic_user,
        )

    long_instr_project = ProjectManager.create(
        name="Long Instructions Test",
        user_performing_action=basic_user,
    )
    long_instructions = "a" * 10000
    result = ProjectManager.set_instructions(
        project_id=long_instr_project.id,
        instructions=long_instructions,
        user_performing_action=basic_user,
    )
    assert result == long_instructions
