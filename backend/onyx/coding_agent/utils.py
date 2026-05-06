import re

import requests

from onyx.coding_agent.mock_tools import GENERATE_ANSWER_TOOL_NAME
from onyx.coding_agent.models import CodingAgentSpecialToolCalls
from onyx.deep_research.dr_mock_tools import THINK_TOOL_NAME
from onyx.tools.models import ToolCallKickoff
from onyx.utils.logger import setup_logger

logger = setup_logger()

GITHUB_TARBALL_URL = "https://api.github.com/repos/{owner}/{repo}/tarball"
GITHUB_DOWNLOAD_TIMEOUT_SECONDS = 60


def parse_github_repo(repo: str) -> tuple[str, str]:
    """Parse a GitHub repo identifier into (owner, name).

    Accepts forms:
        - https://github.com/owner/repo[.git][/...]
        - http://github.com/owner/repo[.git]
        - git@github.com:owner/repo[.git]
        - owner/repo
    """
    repo = repo.strip()

    https_match = re.match(
        r"^https?://github\.com/([^/]+)/([^/?#\s]+?)(?:\.git)?(?:[/?#].*)?$", repo
    )
    if https_match:
        return https_match.group(1), https_match.group(2)

    ssh_match = re.match(r"^git@github\.com:([^/]+)/([^/\s]+?)(?:\.git)?$", repo)
    if ssh_match:
        return ssh_match.group(1), ssh_match.group(2)

    short_match = re.match(r"^([^/\s]+)/([^/\s]+?)(?:\.git)?$", repo)
    if short_match:
        return short_match.group(1), short_match.group(2)

    raise ValueError(f"Could not parse GitHub repo identifier: {repo!r}")


def download_github_repo(repo: str, github_token: str | None = None) -> bytes:
    """Download a GitHub repository as a gzipped tarball.

    Uses GitHub's tarball API. Defaults to the repo's default branch.
    """
    owner, name = parse_github_repo(repo)
    url = GITHUB_TARBALL_URL.format(owner=owner, repo=name)
    headers = {"Accept": "application/vnd.github+json"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"

    logger.info("Downloading GitHub tarball: %s/%s", owner, name)
    response = requests.get(
        url,
        headers=headers,
        timeout=GITHUB_DOWNLOAD_TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.content


def check_special_tool_calls(
    tool_calls: list[ToolCallKickoff],
) -> CodingAgentSpecialToolCalls:
    think_tool_call: ToolCallKickoff | None = None
    generate_answer_tool_call: ToolCallKickoff | None = None

    for tool_call in tool_calls:
        if tool_call.tool_name == THINK_TOOL_NAME:
            think_tool_call = tool_call
        elif tool_call.tool_name == GENERATE_ANSWER_TOOL_NAME:
            generate_answer_tool_call = tool_call

    return CodingAgentSpecialToolCalls(
        think_tool_call=think_tool_call,
        generate_answer_tool_call=generate_answer_tool_call,
    )
