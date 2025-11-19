from collections.abc import Callable
from collections.abc import Generator
from contextlib import contextmanager

from sqlalchemy import Engine
from sqlalchemy import event
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker
from sqlalchemy.orm.session import SessionTransaction

from onyx.agents.agent_search.dr.enums import ResearchType
from onyx.chat.chat_utils import prepare_chat_message_request
from onyx.chat.process_message import gather_stream
from onyx.chat.process_message import stream_chat_message_objects
from onyx.context.search.models import RetrievalDetails
from onyx.db.engine.sql_engine import get_sqlalchemy_engine
from onyx.db.users import get_user_by_email
from onyx.evals.models import EvalationAck
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvalProvider
from onyx.evals.provider import get_default_provider
from shared_configs.contextvars import get_current_tenant_id


@contextmanager
def isolated_ephemeral_session_factory(
    engine: Engine,
) -> Generator[Callable[[], Session], None, None]:
    """
    Create a session factory that creates sessions that run in a transaction that gets rolled back.
    This is useful for running evals without any lasting db side effects.
    """
    tenant_id = get_current_tenant_id()
    schema_translate_map = {None: tenant_id}
    conn = engine.connect().execution_options(schema_translate_map=schema_translate_map)
    outer_tx = conn.begin()
    Maker = sessionmaker(bind=conn, expire_on_commit=False, future=True)

    def make_session() -> Session:
        s = Maker()
        s.begin_nested()

        @event.listens_for(s, "after_transaction_end")
        def _restart_savepoint(
            session: Session, transaction: SessionTransaction
        ) -> None:
            if transaction.nested and not (
                transaction._parent is not None and transaction._parent.nested
            ):
                session.begin_nested()

        return s

    try:
        yield make_session
    finally:
        outer_tx.rollback()
        conn.close()


def _get_answer(
    eval_input: dict[str, str],
    configuration: EvalConfigurationOptions,
) -> str:
    engine = get_sqlalchemy_engine()
    with isolated_ephemeral_session_factory(engine) as SessionLocal:
        with SessionLocal() as db_session:
            full_configuration = configuration.get_configuration(db_session)
            user = (
                get_user_by_email(configuration.search_permissions_email, db_session)
                if configuration.search_permissions_email
                else None
            )
            research_type = ResearchType(eval_input.get("research_type", "THOUGHTFUL"))
            request = prepare_chat_message_request(
                message_text=eval_input["message"],
                user=user,
                persona_id=None,
                persona_override_config=full_configuration.persona_override_config,
                message_ts_to_respond_to=None,
                retrieval_details=RetrievalDetails(),
                rerank_settings=None,
                db_session=db_session,
                skip_gen_ai_answer_generation=False,
                llm_override=full_configuration.llm,
                use_agentic_search=research_type == ResearchType.DEEP,
                allowed_tool_ids=full_configuration.allowed_tool_ids,
            )
            packets = stream_chat_message_objects(
                new_msg_req=request,
                user=user,
                db_session=db_session,
            )
            answer = gather_stream(packets)
            return answer.answer


def run_eval(
    configuration: EvalConfigurationOptions,
    data: list[dict[str, dict[str, str]]] | None = None,
    remote_dataset_name: str | None = None,
    provider: EvalProvider = get_default_provider(),
) -> EvalationAck:
    if data is not None and remote_dataset_name is not None:
        raise ValueError("Cannot specify both data and remote_dataset_name")

    if data is None and remote_dataset_name is None:
        raise ValueError("Must specify either data or remote_dataset_name")

    return provider.eval(
        task=lambda eval_input: _get_answer(eval_input, configuration),
        configuration=configuration,
        data=data,
        remote_dataset_name=remote_dataset_name,
    )
