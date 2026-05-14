"""Manual test harness for the coding-agent loop.

Usage (from repo root, with venv active and Onyx services running):

    source .venv/bin/activate
    python -m backend.scripts.coding_agent_test \\
        --repo onyx-dot-app/onyx \\
        --query "What does the docprocessing celery worker do?"

Optional flags:
    --github-token <pat>   Personal access token for private repos / higher rate limit
    --dump-packets         Print every emitter packet that was streamed during the run
    --max-packets-shown N  Limit how many packets are printed (default 50)

The script wires up the same primitives the chat flow does (SqlEngine,
default LLM, token counter, in-memory emitter + state container) and then
calls run_coding_agent_call directly so you can iterate on the loop without
spinning up the full chat backend.
"""

from __future__ import annotations

import argparse
import queue
from uuid import uuid4

from onyx.chat.emitter import Emitter
from onyx.coding_agent.mock_tools import CODING_AGENT_QUERY_KEY
from onyx.coding_agent.mock_tools import CODING_AGENT_REPO_KEY
from onyx.coding_agent.mock_tools import CODING_AGENT_TOOL_NAME
from onyx.db.engine.sql_engine import get_session_with_current_tenant
from onyx.db.engine.sql_engine import SqlEngine
from onyx.db.models import User
from onyx.llm.factory import get_default_llm
from onyx.llm.factory import get_llm_token_counter
from onyx.server.query_and_chat.placement import Placement
from onyx.tools.fake_tools.coding_agent import run_coding_agent_call
from onyx.tools.models import ToolCallKickoff
from onyx.utils.logger import setup_logger

logger = setup_logger()


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--repo",
        required=True,
        help="GitHub repo as 'owner/name', https URL, or git@ URL",
    )
    parser.add_argument(
        "--query",
        required=True,
        help="The question to ask the coding agent about the repo",
    )
    parser.add_argument(
        "--github-token",
        default=None,
        help="Optional GitHub PAT (private repos / higher rate limit)",
    )
    parser.add_argument(
        "--dump-packets",
        action="store_true",
        help="Print emitter packets that were streamed during the run",
    )
    parser.add_argument(
        "--max-packets-shown",
        type=int,
        default=50,
        help="Cap on how many packets to print when --dump-packets is set",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()

    SqlEngine.set_app_name("coding_agent_test")
    SqlEngine.init_engine(pool_size=5, max_overflow=5)

    with get_session_with_current_tenant() as db_session:
        # Token counter needs an LLM but the agent loop doesn't need a user / persona
        # — repo + query are enough — so we just verify a user exists for parity
        # with the research_agent test harness.
        user = db_session.query(User).first()
        if user is None:
            logger.warning(
                "No users found in DB; continuing anyway since the coding agent "
                "doesn't depend on user context."
            )

        llm = get_default_llm()
        token_counter = get_llm_token_counter(llm)

        emitter_queue: queue.Queue = queue.Queue()
        emitter = Emitter(merged_queue=emitter_queue)

        coding_agent_call = ToolCallKickoff(
            tool_call_id=str(uuid4()),
            tool_name=CODING_AGENT_TOOL_NAME,
            tool_args={
                CODING_AGENT_QUERY_KEY: args.query,
                CODING_AGENT_REPO_KEY: args.repo,
            },
            placement=Placement(turn_index=0, tab_index=0),
        )

        logger.info("Repo: %s", args.repo)
        logger.info("Query: %s", args.query)
        logger.info("LLM: %s/%s", llm.config.model_provider, llm.config.model_name)

        result = run_coding_agent_call(
            coding_agent_call=coding_agent_call,
            emitter=emitter,
            llm=llm,
            token_counter=token_counter,
            user_identity=None,
            github_token=args.github_token,
        )

        if result is None:
            logger.error("Coding agent returned no result (see traceback above)")
            return 1

        print("\n" + "=" * 80)
        print("CODING AGENT ANSWER")
        print("=" * 80)
        print(result.answer)
        print("=" * 80)
        print(f"Total packets emitted: {emitter_queue.qsize()}")

        if args.dump_packets:
            print("\n" + "=" * 80)
            print("EMITTER PACKETS")
            print("=" * 80)
            shown = 0
            while not emitter_queue.empty() and shown < args.max_packets_shown:
                packet = emitter_queue.get_nowait()
                print(f"[{shown:03d}] {packet}")
                shown += 1
            remaining = emitter_queue.qsize()
            if remaining:
                print(f"... ({remaining} more packets not shown)")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
