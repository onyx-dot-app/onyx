import requests
from urllib import robotparser
from usp.tree import sitemap_tree_for_homepage
from datetime import datetime
from onyx.utils.logger import setup_logger

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
    if "llmgw.eea.europa.eu" in llm.config.api_base:
        llm._model_kwargs={
            'metadata':{
                "debug_langfuse": True,
                "generation_name": generation,
                "user_id":user.email,
                "session_id": str(chat_session.id),
                "trace_name": user_message.message[:200],
                "trace_id": str(user_message.id)
            }
        }
    return llm
