from contextlib import nullcontext
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from onyx.configs.app_configs import REPO_ARCHIVE_FETCH_TIMEOUT, REPO_ARCHIVE_MAX_BYTES
from onyx.repo_archives.github import GitHubArchiveProvider
from onyx.repo_archives.models import RepoArchive, RepoRevision
from onyx.tools.fake_tools import coding_agent


def test_coding_agent_fetches_and_extracts_repo_with_existing_policy(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "repo.tar.gz"
    archive_path.write_bytes(b"repository archive")
    archive = RepoArchive(
        path=archive_path,
        size=archive_path.stat().st_size,
        revision=RepoRevision(
            repo=GitHubArchiveProvider.repo_ref("onyx-dot-app", "onyx"),
            commit_sha="a" * 40,
        ),
    )
    client = MagicMock()
    client.__enter__.return_value = client
    client.__exit__.return_value = False
    client.upload_file.return_value = "file-id"
    client.create_session.return_value = SimpleNamespace(session_id="session-id")
    client.execute_bash_in_session.return_value = SimpleNamespace(
        exit_code=0,
        stderr="",
    )

    with (
        patch.object(
            coding_agent, "open_repo_archive", return_value=nullcontext(archive)
        ) as open_archive,
        patch.object(coding_agent, "CodeInterpreterClient", return_value=client),
        coding_agent._setup_session(
            repo_ref=GitHubArchiveProvider.repo_ref("onyx-dot-app", "onyx"),
            github_token="secret",
        ) as (session_id, commit_sha),
    ):
        assert session_id == "session-id"
        assert commit_sha == "a" * 40

    provider, repo_ref, ref = open_archive.call_args.args
    assert isinstance(provider, GitHubArchiveProvider)
    assert provider._authorization_header == "Bearer secret"
    assert (repo_ref.owner, repo_ref.name) == ("onyx-dot-app", "onyx")
    assert ref is None
    assert open_archive.call_args.kwargs == {
        "max_size_bytes": REPO_ARCHIVE_MAX_BYTES,
        "timeout": REPO_ARCHIVE_FETCH_TIMEOUT,
    }
    # The archive streams straight off disk instead of being read into memory.
    client.upload_file.assert_called_once()
    uploaded_file, uploaded_name = client.upload_file.call_args.args
    assert uploaded_name == coding_agent.REPO_TARBALL_PATH
    assert Path(uploaded_file.name) == archive_path
    assert uploaded_file.closed
    client.execute_bash_in_session.assert_called_once_with(
        session_id="session-id",
        cmd="tar -xzf repo.tar.gz --strip-components=1 && rm repo.tar.gz && ls",
        timeout_ms=coding_agent.CODING_AGENT_SETUP_TIMEOUT_MS,
    )
    client.delete_session.assert_called_once_with("session-id")
