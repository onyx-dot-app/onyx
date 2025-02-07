import time
from onyx.utils.logger import setup_logger

logger = setup_logger()

sites = ["https://water.europa.eu/freshwater",
        "https://water.europa.eu/marine",
        "https://biodiversity.europa.eu",
        "https://forest.eea.europa.eu/"]

threshold = 5

def wait_for_page(url, page):
    logger.info(f"playwright attempt: {url}")
    found = False
    for site in sites:
        found = found or url.startswith(site)
    if not found:
        return page
    page.wait_for_load_state("networkidle", timeout=300000)
    page.wait_for_timeout(1000)

    heights = []
    while True:
        page.keyboard.press("PageDown");

        time.sleep(1)  # Give time for new content to load
        page.wait_for_load_state("networkidle", timeout=300000)

        heights.append(page.evaluate("document.body.scrollHeight"))
        if len(heights) > threshold and heights[-1] == heights[-(1+threshold)]:
            break
    return page
