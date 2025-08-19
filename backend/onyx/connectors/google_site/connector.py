import os
import re
from typing import Any
from typing import cast

from bs4 import BeautifulSoup
from bs4 import Tag

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.file_processing.extract_file_text import load_files_from_zip
from onyx.file_processing.extract_file_text import read_text_file
from onyx.file_processing.html_utils import web_html_cleanup
from onyx.file_store.file_store import get_default_file_store
from onyx.utils.logger import setup_logger

logger = setup_logger()


def a_tag_text_to_path(atag: Tag) -> str:
    page_path = atag.text.strip().lower()
    page_path = re.sub(r"[^a-zA-Z0-9\s]", "", page_path)
    page_path = "-".join(page_path.split())

    return page_path


def find_google_sites_page_path_from_navbar(
    element: BeautifulSoup | Tag, path: str, depth: int
) -> str | None:
    lis = cast(
        list[Tag],
        element.find_all("li", attrs={"data-nav-level": f"{depth}"}),
    )
    for li in lis:
        a = cast(Tag, li.find("a"))
        if a.get("aria-selected") == "true":
            return f"{path}/{a_tag_text_to_path(a)}"
        elif a.get("aria-expanded") == "true":
            sub_path = find_google_sites_page_path_from_navbar(
                element, f"{path}/{a_tag_text_to_path(a)}", depth + 1
            )
            if sub_path:
                return sub_path

    return None


class GoogleSitesConnector(LoadConnector):
    def __init__(
        self,
        zip_path: str,
        base_url: str,
        batch_size: int = INDEX_BATCH_SIZE,
    ):
        self.zip_path = zip_path
        self.base_url = base_url
        self.batch_size = batch_size

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        pass

    def load_from_state(self) -> GenerateDocumentsOutput:
        documents: list[Document] = []

        file_content_io = get_default_file_store().read_file(self.zip_path, mode="b")

        # load the HTML files
        files = load_files_from_zip(file_content_io)
        count = 0
        for file_info, file_io in files:
            # skip non-published files
            if "/PUBLISHED/" not in file_info.filename:
                continue

            file_path, extension = os.path.splitext(file_info.filename)
            if extension != ".html":
                continue

            file_content, _ = read_text_file(file_io)
            soup = BeautifulSoup(file_content, "html.parser")

            # get the link out of the navbar
            header = cast(Tag, soup.find("header"))
            nav = cast(Tag, header.find("nav"))
            path = find_google_sites_page_path_from_navbar(nav, "", 1)
            if not path:
                count += 1
                logger.error(
                    f"Could not find path for '{file_info.filename}'. "
                    + "This page will not have a working link.\n\n"
                    + f"# of broken links so far - {count}"
                )
            logger.info(f"Path to page: {path}")
            # cleanup the hidden `Skip to main content` and `Skip to navigation` that
            # appears at the top of every page
            for div in soup.find_all("div", attrs={"data-is-touch-wrapper": "true"}):
                div.extract()

            # get the body of the page
            parsed_html = web_html_cleanup(
                soup, additional_element_types_to_discard=["header", "nav"]
            )

            title = parsed_html.title or file_path.split("/")[-1]
            documents.append(
                Document(
                    id=f"{DocumentSource.GOOGLE_SITES.value}:{path}",
                    source=DocumentSource.GOOGLE_SITES,
                    semantic_identifier=title,
                    sections=[
                        TextSection(
                            link=(
                                (self.base_url.rstrip("/") + "/" + path.lstrip("/"))
                                if path
                                else ""
                            ),
                            text=parsed_html.cleaned_text,
                        )
                    ],
                    metadata={},
                )
            )

            if len(documents) >= self.batch_size:
                yield documents
                documents = []

        if documents:
            yield documents


if __name__ == "__main__":
    connector = GoogleSitesConnector(
        os.environ["GOOGLE_SITES_ZIP_PATH"],
        os.environ.get("GOOGLE_SITES_BASE_URL", ""),
    )
    for doc_batch in connector.load_from_state():
        for doc in doc_batch:
            print(doc)
