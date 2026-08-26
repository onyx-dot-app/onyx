import copy
from typing import Any, cast
from uuid import uuid4

from pydantic import BaseModel
from sqlalchemy.orm import Session
from typing_extensions import override

from onyx.chat.emitter import Emitter
from onyx.coding_agent.mock_tools import (
    CODING_AGENT_QUERY_KEY,
    CODING_AGENT_REF_KEY,
    CODING_AGENT_REPO_KEY,
    CODING_AGENT_TOOL_DESCRIPTION,
    CODING_AGENT_TOOL_NAME,
)
from onyx.configs.constants import (
    CODE_FILE_METADATA_TYPE,
    CODE_FILE_PATH_KEY,
    CODE_FILE_REPO_KEY,
    CODE_FILE_TYPE_KEY,
)
from onyx.db.credentials import fetch_github_access_token_for_repo
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.llm.factory import get_llm_token_counter
from onyx.llm.interfaces import LLM
from onyx.repo_archives.github import GitHubArchiveProvider
from onyx.repo_archives.models import RepoRef
from onyx.server.query_and_chat.placement import Placement
from onyx.server.query_and_chat.streaming_models import CodingAgentStart, Packet
from onyx.tools.interface import Tool
from onyx.tools.models import ToolCallException, ToolCallKickoff, ToolResponse
from onyx.tools.tool_implementations.bash.bash_tool import BashTool
from onyx.utils.logger import setup_logger

logger = setup_logger()

# Upper bound on seed file paths handed to the coding agent's opening prompt.
MAX_SEED_PATHS = 10
# Code chunks pulled from the index per seed-path lookup. Several chunks
# usually map to the same file, so this sits well above MAX_SEED_PATHS.
SEED_PATH_CHUNKS_TO_RETRIEVE = 50


class CodingAgentToolOverrideKwargs(BaseModel):
    pass


class CodingAgentTool(Tool[CodingAgentToolOverrideKwargs]):
    """Top-level Tool wrapper around the coding-agent loop.

    Exposes a single LLM-facing tool that takes a query + GitHub repo,
    runs the inner agent loop (downloads repo, opens a code-interpreter
    session, drives bash commands), and returns the final text answer
    as the tool response.
    """

    NAME = CODING_AGENT_TOOL_NAME
    DISPLAY_NAME = "Coding Agent"
    # UI/DB-facing summary only. The LLM sees
    # CODING_AGENT_TOOL_DESCRIPTION via tool_definition().
    DESCRIPTION = (
        "Deep investigation of a GitHub repository in an isolated sandbox. "
        "Slow and expensive; for cross-file tracing and code verification, "
        "not for simple lookups the code search index answers."
    )

    def __init__(
        self,
        tool_id: int,
        emitter: Emitter,
        llm: LLM,
    ) -> None:
        super().__init__(emitter=emitter)
        self._id = tool_id
        self._llm = llm

    @property
    def id(self) -> int:
        return self._id

    @property
    def name(self) -> str:
        return self.NAME

    @property
    def description(self) -> str:
        return self.DESCRIPTION

    @property
    def display_name(self) -> str:
        return self.DISPLAY_NAME

    @override
    @classmethod
    def is_available(cls, db_session: Session) -> bool:
        """Available iff ``BashTool`` is available."""
        return BashTool.is_available(db_session)

    @override
    def tool_definition(self) -> dict:
        # Single source of truth shared with the deep-research mock-tool path.
        return copy.deepcopy(CODING_AGENT_TOOL_DESCRIPTION)

    @override
    def emit_start(self, placement: Placement) -> None:
        # query and repo aren't bound until run(); CodingAgentStart is emitted
        # there, mirroring PythonTool's pattern.
        return

    @staticmethod
    def _fetch_seed_paths(
        db_session: Session,
        query: str,
        repo_ref: RepoRef,
        limit: int = MAX_SEED_PATHS,
    ) -> list[str]:
        """File paths from the code index most relevant to ``query``.

        Keyword retrieval over indexed GitHub source-code docs, restricted to
        ``repo_ref``. The query runs without a per-user ACL, so callers must
        only invoke this for repos whose indexed docs are org-visible —
        ``run()`` gates on the org-public connector-token eligibility for
        exactly this reason. Failures degrade to an unseeded run.
        """
        # Imported lazily: the document-index/search stack must stay off the
        # tool-construction import path.
        from onyx.configs.constants import DocumentSource
        from onyx.context.search.models import IndexFilters, Tag
        from onyx.db.search_settings import get_current_search_settings
        from onyx.document_index.factory import get_default_document_index
        from shared_configs.contextvars import get_current_tenant_id

        repo_full_name = repo_ref.display.lower()
        try:
            search_settings = get_current_search_settings(db_session)
            document_index = get_default_document_index(
                search_settings, None, db_session
            )
            chunks = document_index.keyword_retrieval(
                query=query,
                filters=IndexFilters(
                    source_type=[DocumentSource.GITHUB],
                    # PRs, issues and docs from the same connector also carry
                    # a repo tag; only source-code docs have a path, so spend
                    # the whole budget on them.
                    tags=[
                        Tag(
                            tag_key=CODE_FILE_TYPE_KEY,
                            tag_value=CODE_FILE_METADATA_TYPE,
                        )
                    ],
                    access_control_list=None,
                    tenant_id=get_current_tenant_id(),
                ),
                num_to_retrieve=SEED_PATH_CHUNKS_TO_RETRIEVE,
            )
        except Exception:
            logger.warning(
                "Seed-path retrieval failed; running coding agent unseeded",
                exc_info=True,
            )
            return []

        paths: list[str] = []
        for chunk in chunks:
            # Repo is compared in Python, not as a tag filter: the index match
            # is case-sensitive and the repo string comes from the LLM.
            if (
                str(chunk.metadata.get(CODE_FILE_REPO_KEY, "")).lower()
                != repo_full_name
            ):
                continue
            path = chunk.metadata.get(CODE_FILE_PATH_KEY)
            if isinstance(path, str) and path not in paths:
                paths.append(path)
            if len(paths) >= limit:
                break
        return paths

    @staticmethod
    def _fetch_connector_token(db_session: Session, repo_ref: RepoRef) -> str | None:
        """Token of the GitHub connector that indexes ``repo_ref``, from the DB.

        Only org-public connector pairs are eligible (see
        fetch_github_access_token_for_repo). None → public-repo access only.
        """
        token = fetch_github_access_token_for_repo(
            db_session=db_session,
            repo_owner=repo_ref.owner,
            repo_name=repo_ref.name,
        )
        if token:
            logger.info(
                "Using GitHub connector credential for coding agent repo %s",
                repo_ref.display,
            )
        return token

    @override
    def run(
        self,
        placement: Placement,
        override_kwargs: CodingAgentToolOverrideKwargs,
        **llm_kwargs: Any,
    ) -> ToolResponse:
        if CODING_AGENT_QUERY_KEY not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing '{CODING_AGENT_QUERY_KEY}' in coding_agent call",
                llm_facing_message=(
                    f"The {self.name} tool requires a "
                    f"'{CODING_AGENT_QUERY_KEY}' parameter."
                ),
            )
        if CODING_AGENT_REPO_KEY not in llm_kwargs:
            raise ToolCallException(
                message=f"Missing '{CODING_AGENT_REPO_KEY}' in coding_agent call",
                llm_facing_message=(
                    f"The {self.name} tool requires a "
                    f"'{CODING_AGENT_REPO_KEY}' parameter."
                ),
            )
        query = cast(str, llm_kwargs[CODING_AGENT_QUERY_KEY])
        repo = cast(str, llm_kwargs[CODING_AGENT_REPO_KEY])
        ref = cast(str | None, llm_kwargs.get(CODING_AGENT_REF_KEY))

        # Parsed once here and threaded through; everything downstream takes
        # the RepoRef rather than re-parsing the LLM-supplied string.
        try:
            repo_ref = GitHubArchiveProvider.repo_ref_from_url(repo)
        except Exception as e:
            raise ToolCallException(
                message=f"Unparseable '{CODING_AGENT_REPO_KEY}' value {repo!r}: {e}",
                llm_facing_message=(
                    f"'{repo}' is not a valid GitHub repository. Pass either "
                    "'owner/repo' or a github.com repository URL."
                ),
            )

        self.emitter.emit(
            Packet(
                placement=placement,
                obj=CodingAgentStart(query=query, repo=repo),
            )
        )

        # Imported lazily to avoid a circular import: coding_agent.py imports
        # the BashTool which lives in tool_implementations alongside us.
        from onyx.tools.fake_tools.coding_agent import run_coding_agent_call

        with get_session_with_current_tenant() as db_session:
            connector_token = self._fetch_connector_token(db_session, repo_ref)
            # Seed only when an org-public connector pair covers this repo:
            # seed retrieval runs without a per-user ACL, so it must be
            # limited to repos whose indexed docs every org member may see. A
            # None token means no such pair exists (permission-synced or
            # unindexed repo) — run unseeded rather than leak file paths
            # through the agent prompt.
            seed_paths = (
                self._fetch_seed_paths(db_session, query, repo_ref)
                if connector_token
                else []
            )

        synthetic_call = ToolCallKickoff(
            tool_call_id=str(uuid4()),
            tool_name=self.name,
            tool_args={
                CODING_AGENT_QUERY_KEY: query,
                CODING_AGENT_REPO_KEY: repo,
                **({CODING_AGENT_REF_KEY: ref} if ref else {}),
            },
            placement=placement,
        )

        token_counter = get_llm_token_counter(self._llm)

        result = run_coding_agent_call(
            coding_agent_call=synthetic_call,
            emitter=self.emitter,
            llm=self._llm,
            token_counter=token_counter,
            user_identity=None,
            github_token=connector_token,
            seed_paths=seed_paths,
            repo_ref=repo_ref,
        )

        if result is None:
            failure_msg = (
                "Coding agent failed to produce an answer. "
                "Check the server logs for the underlying error."
            )
            logger.warning("Coding agent run returned None for query: %s", query)
            return ToolResponse(
                rich_response=None,
                llm_facing_response=failure_msg,
            )

        return ToolResponse(
            rich_response=result.answer,
            llm_facing_response=result.answer,
        )
