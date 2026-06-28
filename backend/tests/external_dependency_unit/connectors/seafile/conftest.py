import io
import os
import shutil
import subprocess
import time
import zipfile
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import openpyxl
import pytest
import requests
from openpyxl.worksheet.worksheet import Worksheet

SEAFILE_ADMIN_EMAIL = "seafile-test@example.com"
SEAFILE_ADMIN_PASSWORD = "seafile-test-password"
SEAFILE_COMPOSE_PROJECT = "onyx-seafile-test"
SEAFILE_TEST_PORT = "18080"
SEAFILE_READY_TIMEOUT_SECONDS = 180


@dataclass(frozen=True)
class SeafileTestLibrary:
    base_url: str
    api_token: str
    repo_id: str
    library_name: str
    seeded_text_files: dict[str, str]
    seeded_private_files: dict[str, str]
    seeded_csv_files: dict[str, str]
    seeded_parser_files: dict[str, str]
    seeded_large_files: dict[str, str]
    seeded_unsupported_files: set[str]


def _compose_file_path() -> Path:
    return Path(__file__).with_name("docker-compose.yml")


def _compose_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("SEAFILE_TEST_PORT", SEAFILE_TEST_PORT)
    env.setdefault("INIT_SEAFILE_ADMIN_EMAIL", SEAFILE_ADMIN_EMAIL)
    env.setdefault("INIT_SEAFILE_ADMIN_PASSWORD", SEAFILE_ADMIN_PASSWORD)
    return env


def _docker_compose_cmd() -> list[str]:
    return [
        "docker",
        "compose",
        "-p",
        SEAFILE_COMPOSE_PROJECT,
        "-f",
        str(_compose_file_path()),
    ]


def _run_compose(
    args: list[str], *, check: bool = True
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [*_docker_compose_cmd(), *args],
        check=check,
        capture_output=True,
        env=_compose_env(),
        text=True,
    )


def _skip_if_docker_unavailable() -> None:
    if shutil.which("docker") is None:
        pytest.skip("Docker is required for the Seafile container fixture")

    compose_result = subprocess.run(
        ["docker", "compose", "version"],
        capture_output=True,
        text=True,
        check=False,
    )
    if compose_result.returncode != 0:
        pytest.skip("Docker Compose is required for the Seafile container fixture")

    daemon_result = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        text=True,
        check=False,
    )
    if daemon_result.returncode != 0:
        if os.environ.get("CI") == "true":
            raise RuntimeError(
                "Docker is required for the Seafile container fixture in CI.\n"
                f"{daemon_result.stdout}\n{daemon_result.stderr}"
            )
        pytest.skip("Docker daemon is not available for the Seafile container fixture")

    compose_query_result = _run_compose(["ps"], check=False)
    if compose_query_result.returncode != 0:
        if os.environ.get("CI") == "true":
            raise RuntimeError(
                "Docker Compose cannot query the Seafile test project in CI.\n"
                f"{compose_query_result.stdout}\n{compose_query_result.stderr}"
            )
        pytest.skip("Docker Compose cannot query the Seafile test project")


def _wait_for_seafile(base_url: str) -> None:
    deadline = time.monotonic() + SEAFILE_READY_TIMEOUT_SECONDS
    last_error: Exception | None = None

    while time.monotonic() < deadline:
        try:
            response = requests.get(f"{base_url}/api2/ping/", timeout=5)
            if (
                response.status_code == 200
                and response.text.strip().strip('"') == "pong"
            ):
                return
        except requests.RequestException as exc:
            last_error = exc
        time.sleep(2)

    logs = _run_compose(["logs", "--no-color", "--tail=200"], check=False)
    raise TimeoutError(
        "Timed out waiting for Seafile test container. "
        f"Last error: {last_error}\n{logs.stdout}\n{logs.stderr}"
    )


def _get_api_token(base_url: str) -> str:
    response = requests.post(
        f"{base_url}/api2/auth-token/",
        data={
            "username": SEAFILE_ADMIN_EMAIL,
            "password": SEAFILE_ADMIN_PASSWORD,
        },
        timeout=10,
    )
    response.raise_for_status()
    data = response.json()
    token = data.get("token")
    assert isinstance(token, str)
    return token


def _request_json(
    method: str,
    url: str,
    api_token: str,
    **kwargs: Any,
) -> Any:
    response = requests.request(
        method,
        url,
        headers={"Authorization": f"Token {api_token}"},
        timeout=20,
        **kwargs,
    )
    response.raise_for_status()
    return response.json()


def _create_library(base_url: str, api_token: str) -> tuple[str, str]:
    library_name = f"onyx-seafile-test-{int(time.time())}"
    data = _request_json(
        "POST",
        f"{base_url}/api2/repos/",
        api_token,
        data={
            "name": library_name,
            "desc": "Onyx Seafile connector test library",
        },
    )
    repo_id = data.get("repo_id")
    assert isinstance(repo_id, str)
    return repo_id, library_name


def _create_directory(base_url: str, api_token: str, repo_id: str, path: str) -> None:
    response = requests.post(
        f"{base_url}/api2/repos/{repo_id}/dir/",
        headers={"Authorization": f"Token {api_token}"},
        params={"p": path},
        data={"operation": "mkdir"},
        timeout=20,
    )
    if response.status_code not in {200, 201, 409}:
        response.raise_for_status()


def _upload_file(
    base_url: str,
    api_token: str,
    repo_id: str,
    parent_dir: str,
    filename: str,
    content: bytes,
    content_type: str,
) -> None:
    upload_link = _request_json(
        "GET",
        f"{base_url}/api2/repos/{repo_id}/upload-link/",
        api_token,
        params={"p": parent_dir},
    )
    assert isinstance(upload_link, str)

    response = requests.post(
        upload_link,
        data={"parent_dir": parent_dir, "replace": "1"},
        files={"file": (filename, content, content_type)},
        timeout=20,
    )
    response.raise_for_status()


def overwrite_file(
    base_url: str,
    api_token: str,
    repo_id: str,
    path: str,
    content: bytes,
    content_type: str = "text/plain",
) -> None:
    parent_dir, filename = path.rsplit("/", 1)
    _upload_file(
        base_url=base_url,
        api_token=api_token,
        repo_id=repo_id,
        parent_dir=parent_dir,
        filename=filename,
        content=content,
        content_type=content_type,
    )


def delete_file(base_url: str, api_token: str, repo_id: str, path: str) -> None:
    response = requests.delete(
        f"{base_url}/api2/repos/{repo_id}/file/",
        headers={"Authorization": f"Token {api_token}"},
        params={"p": path},
        timeout=20,
    )
    if response.status_code not in {200, 202, 204, 404}:
        response.raise_for_status()


def move_file(
    base_url: str,
    api_token: str,
    repo_id: str,
    source_path: str,
    destination_dir: str,
) -> None:
    response = requests.post(
        f"{base_url}/api2/repos/{repo_id}/file/",
        headers={"Authorization": f"Token {api_token}"},
        params={"p": source_path},
        data={
            "operation": "move",
            "dst_repo": repo_id,
            "dst_dir": destination_dir,
        },
        timeout=20,
    )
    response.raise_for_status()


def delete_directory(base_url: str, api_token: str, repo_id: str, path: str) -> None:
    response = requests.delete(
        f"{base_url}/api2/repos/{repo_id}/dir/",
        headers={"Authorization": f"Token {api_token}"},
        params={"p": path},
        timeout=20,
    )
    if response.status_code not in {200, 202, 204, 404}:
        response.raise_for_status()


def _make_xlsm_content() -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    assert isinstance(worksheet, Worksheet)
    worksheet.title = "Parser"
    worksheet.append(["kind", "value"])
    worksheet.append(["xlsm-parser", "macro workbook text"])
    content = io.BytesIO()
    workbook.save(content)
    return content.getvalue()


def _make_epub_content() -> bytes:
    content = io.BytesIO()
    with zipfile.ZipFile(content, "w") as epub:
        epub.writestr("mimetype", "application/epub+zip")
        epub.writestr(
            "chapter.xhtml",
            "<html><body><h1>Parser EPUB</h1><p>epub parser text</p></body></html>",
        )
    return content.getvalue()


def _delete_library(base_url: str, api_token: str, repo_id: str) -> None:
    response = requests.delete(
        f"{base_url}/api2/repos/{repo_id}/",
        headers={"Authorization": f"Token {api_token}"},
        timeout=20,
    )
    if response.status_code not in {200, 202, 204, 404}:
        response.raise_for_status()


@pytest.fixture(scope="session")
def seafile_test_library() -> Iterator[SeafileTestLibrary]:
    external_base_url = os.environ.get("SEAFILE_TEST_BASE_URL")
    test_port = os.environ.get("SEAFILE_TEST_PORT", SEAFILE_TEST_PORT)
    base_url = external_base_url or f"http://127.0.0.1:{test_port}"
    stack_started = external_base_url is None

    if stack_started:
        _skip_if_docker_unavailable()
        _run_compose(["down", "-v", "--remove-orphans"], check=False)
        _run_compose(["up", "-d"])

    try:
        _wait_for_seafile(base_url)
        api_token = _get_api_token(base_url)
        repo_id, library_name = _create_library(base_url, api_token)
        _create_directory(base_url, api_token, repo_id, "/docs")
        _create_directory(base_url, api_token, repo_id, "/private")

        seeded_text_files = {
            "/docs/readme.txt": "Seafile connector fixture readme\n",
            "/docs/nested-notes.md": "# Nested notes\nIndexed from Seafile CE\n",
        }
        for path, content in seeded_text_files.items():
            parent_dir, filename = path.rsplit("/", 1)
            _upload_file(
                base_url=base_url,
                api_token=api_token,
                repo_id=repo_id,
                parent_dir=parent_dir,
                filename=filename,
                content=content.encode("utf-8"),
                content_type="text/plain",
            )

        seeded_private_files = {
            "/private/secret.txt": "This file must not be indexed from /docs\n",
        }
        for path, content in seeded_private_files.items():
            parent_dir, filename = path.rsplit("/", 1)
            _upload_file(
                base_url=base_url,
                api_token=api_token,
                repo_id=repo_id,
                parent_dir=parent_dir,
                filename=filename,
                content=content.encode("utf-8"),
                content_type="text/plain",
            )

        seeded_csv_files = {
            "/docs/table.csv": "name,value\nalpha,1\nbeta,2\n",
        }
        for path, content in seeded_csv_files.items():
            parent_dir, filename = path.rsplit("/", 1)
            _upload_file(
                base_url=base_url,
                api_token=api_token,
                repo_id=repo_id,
                parent_dir=parent_dir,
                filename=filename,
                content=content.encode("utf-8"),
                content_type="text/csv",
            )

        seeded_parser_files = {
            "/docs/message.eml": "eml parser text",
            "/docs/book.epub": "epub parser text",
            "/docs/macro.xlsm": "xlsm-parser,macro workbook text",
        }
        _upload_file(
            base_url=base_url,
            api_token=api_token,
            repo_id=repo_id,
            parent_dir="/docs",
            filename="message.eml",
            content=(
                "From: seafile-test@example.com\n"
                "To: onyx-test@example.com\n"
                "Subject: Parser email\n"
                "\n"
                "eml parser text\n"
            ).encode("utf-8"),
            content_type="message/rfc822",
        )
        _upload_file(
            base_url=base_url,
            api_token=api_token,
            repo_id=repo_id,
            parent_dir="/docs",
            filename="book.epub",
            content=_make_epub_content(),
            content_type="application/epub+zip",
        )
        _upload_file(
            base_url=base_url,
            api_token=api_token,
            repo_id=repo_id,
            parent_dir="/docs",
            filename="macro.xlsm",
            content=_make_xlsm_content(),
            content_type=("application/vnd.ms-excel.sheet.macroEnabled.12"),
        )

        seeded_large_files = {
            "/docs/large.txt": "large-file-content-" * 32,
        }
        for path, content in seeded_large_files.items():
            parent_dir, filename = path.rsplit("/", 1)
            _upload_file(
                base_url=base_url,
                api_token=api_token,
                repo_id=repo_id,
                parent_dir=parent_dir,
                filename=filename,
                content=content.encode("utf-8"),
                content_type="text/plain",
            )

        seeded_unsupported_files = {"/docs/skipped-archive.zip"}
        _upload_file(
            base_url=base_url,
            api_token=api_token,
            repo_id=repo_id,
            parent_dir="/docs",
            filename="skipped-archive.zip",
            content=b"not indexed by Seafile connector",
            content_type="application/zip",
        )

        yield SeafileTestLibrary(
            base_url=base_url,
            api_token=api_token,
            repo_id=repo_id,
            library_name=library_name,
            seeded_text_files=seeded_text_files,
            seeded_private_files=seeded_private_files,
            seeded_csv_files=seeded_csv_files,
            seeded_parser_files=seeded_parser_files,
            seeded_large_files=seeded_large_files,
            seeded_unsupported_files=seeded_unsupported_files,
        )
    finally:
        if "api_token" in locals() and "repo_id" in locals():
            _delete_library(base_url, api_token, repo_id)
        if stack_started:
            _run_compose(["down", "-v", "--remove-orphans"], check=False)


@pytest.fixture
def seafile_second_test_library(
    seafile_test_library: SeafileTestLibrary,
) -> Iterator[SeafileTestLibrary]:
    base_url = seafile_test_library.base_url
    api_token = seafile_test_library.api_token
    repo_id, library_name = _create_library(base_url, api_token)

    try:
        _create_directory(base_url, api_token, repo_id, "/docs")
        seeded_text_files = {
            "/docs/second-library.txt": "Second Seafile library fixture content\n",
        }
        for path, content in seeded_text_files.items():
            parent_dir, filename = path.rsplit("/", 1)
            _upload_file(
                base_url=base_url,
                api_token=api_token,
                repo_id=repo_id,
                parent_dir=parent_dir,
                filename=filename,
                content=content.encode("utf-8"),
                content_type="text/plain",
            )

        yield SeafileTestLibrary(
            base_url=base_url,
            api_token=api_token,
            repo_id=repo_id,
            library_name=library_name,
            seeded_text_files=seeded_text_files,
            seeded_private_files={},
            seeded_csv_files={},
            seeded_parser_files={},
            seeded_large_files={},
            seeded_unsupported_files=set(),
        )
    finally:
        _delete_library(base_url, api_token, repo_id)


@pytest.fixture
def seafile_mutation_test_library(
    seafile_test_library: SeafileTestLibrary,
) -> Iterator[SeafileTestLibrary]:
    base_url = seafile_test_library.base_url
    api_token = seafile_test_library.api_token
    repo_id, library_name = _create_library(base_url, api_token)

    try:
        _create_directory(base_url, api_token, repo_id, "/docs")
        _create_directory(base_url, api_token, repo_id, "/docs/moved")
        _create_directory(base_url, api_token, repo_id, "/docs/obsolete")
        _create_directory(base_url, api_token, repo_id, "/private")

        seeded_text_files = {
            "/docs/readme.txt": "Mutation fixture readme original\n",
            "/docs/delete-me.txt": "Mutation fixture delete target\n",
            "/docs/move-me.txt": "Mutation fixture move target\n",
            "/docs/obsolete/stale.txt": "Mutation fixture stale folder target\n",
        }
        seeded_private_files = {
            "/private/scope-change.txt": "Mutation fixture private scope target\n",
        }

        for path, content in {
            **seeded_text_files,
            **seeded_private_files,
        }.items():
            parent_dir, filename = path.rsplit("/", 1)
            _upload_file(
                base_url=base_url,
                api_token=api_token,
                repo_id=repo_id,
                parent_dir=parent_dir,
                filename=filename,
                content=content.encode("utf-8"),
                content_type="text/plain",
            )

        yield SeafileTestLibrary(
            base_url=base_url,
            api_token=api_token,
            repo_id=repo_id,
            library_name=library_name,
            seeded_text_files=seeded_text_files,
            seeded_private_files=seeded_private_files,
            seeded_csv_files={},
            seeded_parser_files={},
            seeded_large_files={},
            seeded_unsupported_files=set(),
        )
    finally:
        _delete_library(base_url, api_token, repo_id)
