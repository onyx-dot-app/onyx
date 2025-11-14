from datetime import datetime
import json
import os
import requests
from urllib import robotparser
from sqlalchemy.orm import Session
import xml.etree.ElementTree as ET

from fastapi import Depends
from langfuse import Langfuse
from usp.tree import sitemap_tree_for_homepage

from onyx.auth.users import current_curator_or_admin_user
from onyx.db.engine.sql_engine import get_session
from onyx.db.enums import ConnectorCredentialPairStatus
from onyx.db.models import ChatMessage, User
from onyx.configs.constants import DANSWER_API_KEY_PREFIX, DocumentSource
from onyx.server.models import StatusResponse
from onyx.utils.logger import setup_logger

LANGFUSE_SECRET_KEY = os.environ.get("LANGFUSE_SECRET_KEY")
LANGFUSE_PUBLIC_KEY = os.environ.get("LANGFUSE_PUBLIC_KEY")
LANGFUSE_HOST = os.environ.get("LANGFUSE_HOST", None)
SOER_LOGIN = os.environ.get("SOER_LOGIN")
SOER_PASSWORD = os.environ.get("SOER_PASSWORD")

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
    urls_data = {}
    tree = sitemap_tree_for_homepage(site)
    for page in tree.all_pages():
        if test_url(rp, page):
            urls_data[page.url] = page.last_modified
    return urls_data

def soer_login():
    login_url = "https://www.eea.europa.eu/++api++/@login"
    payload = {
        "login": SOER_LOGIN,
        "password": SOER_PASSWORD
    }

    headers = {
        'accept': 'application/json',
    }

    session = requests.Session()

    response = session.post(login_url, json=payload, headers=headers)

    resp = {
        'authenticated': False,
    }
    if response.ok:
        __ac__eea = ""
        for cookie in session.cookies:
            if cookie.name == '__ac__eea':
                __ac__eea = cookie.value

        resp = {
            'authenticated': True,
            '__ac__eea': cookie.value,
            'auth_token': json.loads(response.text).get("token")
        }
    return resp

def read_protected_sitemap(sitemap, auth):
    urls_data: dict[str, str | None] = {}

    cookies = {'auth_token': auth['auth_token'], "__ac__eea": auth['__ac__eea']}

    response = requests.get(sitemap, cookies=cookies)

    root = ET.fromstring(response.text)

    ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}

    for url in root.findall('.//ns:url', ns):
        loc = url.find('.//ns:loc', ns)
        lastmod = url.find('.//ns:lastmod', ns)
        if loc is not None and loc.text:
            lastmod_value = lastmod.text if lastmod is not None else None
            urls_data[loc.text] = lastmod_value

    return urls_data

def list_pages_for_protected_site_eea(site: str, auth) -> list[str]:
    """Get list of pages from a site's sitemaps"""

    return read_protected_sitemap(site, auth)

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
    final_user_id = f"{user_id} - {chat_session.persona.name}"
    llm._model_kwargs={
        'metadata':{
            "debug_langfuse": True,
            "generation_name": generation,
            "user_id":final_user_id,
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

def remove_by_selector(soup, selector):
    tag = soup.select_one("meta[name='remove_by_selector']")
    if tag and tag.has_attr("content"):
        page_selector = [tag["content"].strip()]
    else:
        page_selector = []

    for sel in (selector + page_selector):
        sel = sel.strip()
        if not sel:
            continue
        for s in sel.split(","):
            s = s.strip()
            if not s:
                continue
            for tag in soup.select(s):
                tag.decompose()

def get_connectors_health(
    user: User = Depends(current_curator_or_admin_user),
    db_session: Session = Depends(get_session),
) -> StatusResponse:
    from onyx.server.documents.connector import get_connector_indexing_status
    indexing_status = get_connector_indexing_status(user = user, db_session = db_session)

    success = True
    message = "ok"

    error_cnt = 0
    connector_cnt = 0
    for connector_status in indexing_status:
        if connector_status.cc_pair_status == ConnectorCredentialPairStatus.ACTIVE and \
            connector_status.connector.source == DocumentSource.WEB and \
            connector_status.connector.refresh_freq <= 86400:
            connector_cnt += 1
            if connector_status.in_repeated_error_state:
                error_cnt += 1
    if connector_cnt > 0:
        if error_cnt == connector_cnt:
            success = False
            message = "Indexing failed"

    return StatusResponse(success=success, message=message)
