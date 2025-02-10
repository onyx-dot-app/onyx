import time
from onyx.utils.logger import setup_logger

logger = setup_logger()

sites = ["https://water.europa.eu/freshwater",
        "https://water.europa.eu/marine",
        "https://biodiversity.europa.eu",
        "https://forest.eea.europa.eu/"]

THRESHOLD = 5
TIMEOUT = 30000

def wait_for_page(url, page):
    logger.info(f"================playwright attempt: {url}=========")

    found = False
    for site in sites:
        found = found or url.startswith(site)
    if not found:
        return page
    page.wait_for_load_state("networkidle", timeout=TIMEOUT)
    page.wait_for_timeout(1000)

    heights = []
    while True:
        page.keyboard.press("PageDown");

        time.sleep(1)  # Give time for new content to load
        page.wait_for_load_state("networkidle", timeout=TIMEOUT)

        heights.append(page.evaluate("document.body.scrollHeight"))
        if len(heights) > THRESHOLD and heights[-1] == heights[-(1+THRESHOLD)]:
            break
    return page


def stop_playwright(browser, playwright):
    try:
        if browser.is_connected():
            for context in browser.contexts:
                for page in context.pages:
                    page.close()
                context.close()

            browser.close()
            playwright.stop()
            logger.info("playwright stopped")
    except Exception as e:
        logger.info("================failed to stop playwright=========")
        pw_error = f"Failed to stop playwright: {e}"
        logger.info(pw_error)
        pass
