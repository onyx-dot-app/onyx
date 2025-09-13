from contextlib import contextmanager
from typing import Any

from braintrust import Dataset
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
from onyx.evals.models import EvalConfigurationOptions
from onyx.evals.models import EvaluationResult
from onyx.evals.provider import get_default_provider
from shared_configs.contextvars import get_current_tenant_id


@contextmanager
def session_factory_context_manager(engine: Engine):
    tenant_id = get_current_tenant_id()
    schema_translate_map = {None: tenant_id}
    conn = engine.connect().execution_options(schema_translate_map=schema_translate_map)
    outer_tx = conn.begin()
    Maker = sessionmaker(bind=conn, expire_on_commit=False, future=True)

    def make_session() -> Session:
        s = Maker()
        s.begin_nested()

        @event.listens_for(s, "after_transaction_end")
        def _restart_savepoint(session: Session, transaction: SessionTransaction):
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
    input: dict[str, str],
    configuration: EvalConfigurationOptions,
) -> str:
    engine = get_sqlalchemy_engine()
    with session_factory_context_manager(engine) as SessionLocal:
        with SessionLocal() as db_session:
            full_configuration = configuration.get_configuration(db_session)
            user = (
                get_user_by_email(full_configuration.impersonation_email, db_session)
                if full_configuration.impersonation_email
                else None
            )
            research_type = ResearchType(input.get("research_type", "THOUGHTFUL"))
            request = prepare_chat_message_request(
                message_text=input["message"],
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
            )
            packets = stream_chat_message_objects(
                new_msg_req=request,
                user=user,
                db_session=db_session,
            )
            answer = gather_stream(packets)
            return answer.answer


def eval(
    data: Dataset | list[Any], configuration: EvalConfigurationOptions
) -> EvaluationResult:
    provider = get_default_provider()
    return provider.eval(
        configuration,
        lambda input, metadata: _get_answer(input, configuration),
        data,
    )
