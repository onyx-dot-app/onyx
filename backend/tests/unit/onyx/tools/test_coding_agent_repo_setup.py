from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from onyx.tools.fake_tools import coding_agent


def test_coding_agent_downloads_and_extracts_repo_with_existing_policy() -> None:
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
            coding_agent,
            "download_github_archive",
            return_value=b"repository archive",
        ) as download_archive,
        patch.object(coding_agent, "CodeInterpreterClient", return_value=client),
        coding_agent._setup_session(
            repo="git@github.com:onyx-dot-app/onyx.git",
            github_token="secret",
        ) as session_id,
    ):
        assert session_id == "session-id"

    source, revision, authorization = download_archive.call_args.args
    assert (source.owner, source.repo) == ("onyx-dot-app", "onyx")
    assert revision == "HEAD"
    assert authorization == "Bearer secret"
    assert download_archive.call_args.kwargs == {
        "max_size_bytes": 500 * 1024 * 1024,
        "timeout": (30, 300),
    }
    client.upload_file.assert_called_once_with(
        b"repository archive",
        coding_agent.REPO_TARBALL_PATH,
    )
    client.execute_bash_in_session.assert_called_once_with(
        session_id="session-id",
        cmd="tar -xzf repo.tar.gz --strip-components=1 && rm repo.tar.gz && ls",
        timeout_ms=coding_agent.CODING_AGENT_SETUP_TIMEOUT_MS,
    )
    client.delete_session.assert_called_once_with("session-id")
