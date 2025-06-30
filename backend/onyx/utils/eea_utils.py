import requests
from urllib import robotparser
from usp.tree import sitemap_tree_for_homepage
from datetime import datetime
from onyx.utils.logger import setup_logger
from onyx.db.models import ChatMessage
from onyx.configs.constants import DANSWER_API_KEY_PREFIX
import os
from langfuse import Langfuse

LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", None)

langfuse = None

if LANGFUSE_HOST is not None:
    langfuse = Langfuse(
        secret_key=os.environ["LANGFUSE_SECRET_KEY"],
        public_key=os.environ["LANGFUSE_PUBLIC_KEY"],
        host=os.environ["LANGFUSE_HOST"]
    )

logger = setup_logger()

def test_url(rp, url):
    if not rp:
        return True
    else:
        return rp.can_fetch("*", url)

def init_robots_txt(site):
    ts = datetime.now().timestamp()
    robots_url = f"{url}/robots.txt?ts={ts}"
    rp = robotparser.RobotFileParser()
    rp.set_url(robots_url)
    rp.read()
    return rp

def list_pages_for_site_eea(site):
    rp = None
    try:
        rp = init_robots_txt(site)
    except:
        logger.warning("Failed to load robots.txt")
    tree = sitemap_tree_for_homepage(site)
    pages = [page.url for page in tree.all_pages() if test_url(rp, page)]
    pages = list(dict.fromkeys(pages))
    return(pages)

def is_pdf_mime_type(url):
    response = requests.head(url, stream=True)
    content_type = response.headers.get('Content-Type', '')
    logger.info(f"MIME TYPE of {url} : {content_type}")
    if 'application/pdf' in content_type:
        return True
    else:
        return False

def add_metadata_to_llm(llm, generation, user, user_message, chat_session):
    user_id = "anon"
    if user is not None:
        user_id = user.email
    if user_id.startswith(DANSWER_API_KEY_PREFIX.lower()):
        user_id = user_id.split("@")[0].split(DANSWER_API_KEY_PREFIX.lower())[1]
    llm._model_kwargs={
        'metadata':{
            "debug_langfuse": True,
            "generation_name": generation,
            "user_id":user_id,
            "session_id": str(chat_session.id),
            "trace_name": user_message.message[:200],
            "trace_id": str(user_message.id)
        }
    }
    return llm

def score(trace, feedback):
    langfuse.score(
        trace_id = trace.id,
        name = "feedback_is_positive",
        value = feedback.is_positive,
        data_type="BOOLEAN")

    if feedback.feedback_text:
        langfuse.score(
            trace_id = trace.id,
            name = "feedback_text",
            value = feedback.feedback_text)

    if feedback.predefined_feedback:
        langfuse.score(
            trace_id = trace.id,
            name = "feedback_predefined",
            value = feedback.predefined_feedback)


def find_id(message_id, db_session):
    chat_message_list = []
    chat_session_id = None
    while True:
        result = db_session.query(ChatMessage.chat_session_id.label("chat_session_id"), ChatMessage.parent_message.label("parent_message"), ChatMessage.message_type.label("message_type")).where(ChatMessage.id == message_id).all()
        if len(result) == 0:
            break
        chat_message_list.append(message_id)
        chat_session_id = result[0][0].__str__()
        message_id = result[0][1]
        if message_id is None:
            break
    return {"session_id": chat_session_id, "messages": chat_message_list}


def identify_trace(logs, langfuse_traces):
    found_trace = None
    log_cnt = 0
    while True:
        if log_cnt == len(logs):
            break
        log_id = logs[log_cnt]
        log_cnt += 1
        trace_cnt = 0
        while True:
            if trace_cnt == len(langfuse_traces):
                break
            trace = langfuse_traces[trace_cnt]
            trace_cnt += 1
            if trace.id.__str__() == log_id.__str__():
                found_trace = trace
                break
        if found_trace:
            break

    return found_trace

def find_langfuse_trace(pg_logs):
    session_id = pg_logs.get("session_id", None)
    if session_id is None:
        return

    logs = pg_logs.get("messages", [])
    if len(logs) == 0:
        return

    langfuse_traces = []
    page = 1
    while True:
        traces = langfuse.fetch_traces(page=page, limit=50, session_id=session_id)
        if len(traces.data) == 0:
            break
        langfuse_traces += traces.data
        page += 1

    if len(langfuse_traces) == 0:
        return

    trace = identify_trace(logs, langfuse_traces)

    return trace


def send_score_to_langfuse(feedback, db_session):
    if langfuse is None:
        return

    pg_logs = find_id(feedback.chat_message_id, db_session)

    trace = find_langfuse_trace(pg_logs)

    score(trace, feedback)
