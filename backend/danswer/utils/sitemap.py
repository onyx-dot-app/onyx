from urllib import robotparser
from usp.tree import sitemap_tree_for_homepage
from datetime import datetime
from danswer.utils.logger import setup_logger

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

def list_pages_for_site(site):
  rp = None
  try:
    rp = init_robots_txt(site)
  except:
    logger.warning("Failed to load robots.txt")

  tree = sitemap_tree_for_homepage(site)

  pages = [page.url for page in tree.all_pages() if test_url(rp, page)]
  pages = list(dict.fromkeys(pages))

  return(pages)

