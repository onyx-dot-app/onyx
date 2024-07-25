from datetime import datetime
from urllib import robotparser

from usp.tree import sitemap_tree_for_homepage  # type: ignore

from danswer.utils.logger import setup_logger

logger = setup_logger()


def test_url(rp: robotparser.RobotFileParser | None, url: str) -> bool:
    if not rp:
        return True
    else:
        return rp.can_fetch("*", url)


def init_robots_txt(site: str) -> robotparser.RobotFileParser:
    ts = datetime.now().timestamp()
    robots_url = f"{site}/robots.txt?ts={ts}"
    rp = robotparser.RobotFileParser()
    rp.set_url(robots_url)
    rp.read()
    return rp


def list_pages_for_site(site: str) -> list[str]:
    rp: robotparser.RobotFileParser | None = None
    try:
        rp = init_robots_txt(site)
    except Exception:
        logger.warning("Failed to load robots.txt")

    tree = sitemap_tree_for_homepage(site)

    pages = [page.url for page in tree.all_pages() if test_url(rp, page.url)]
    pages = list(dict.fromkeys(pages))

    return pages
