import time
from collections.abc import Iterator
from datetime import datetime
from datetime import timezone
from io import BytesIO
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup
from PIL import Image

from onyx.configs.app_configs import FRESHDESK_API_REQUEST_DELAY_SECONDS
from onyx.configs.app_configs import FRESHDESK_ARTICLE_FETCH_DELAY_SECONDS
from onyx.configs.app_configs import FRESHDESK_ATTACHMENT_BASE_URL
from onyx.configs.app_configs import FRESHDESK_ATTACHMENT_INLINE_PATH
from onyx.configs.app_configs import FRESHDESK_ATTACHMENT_PATH
from onyx.configs.app_configs import FRESHDESK_ATTACHMENT_TOKEN_PARAM
from onyx.configs.app_configs import FRESHDESK_DOMAIN_SUFFIX
from onyx.configs.app_configs import FRESHDESK_ICON_MIN_HEIGHT
from onyx.configs.app_configs import FRESHDESK_ICON_MIN_WIDTH
from onyx.configs.app_configs import FRESHDESK_IMAGE_DOWNLOAD_INTERVAL
from onyx.configs.app_configs import FRESHDESK_IMAGE_REQUEST_TIMEOUT_SECONDS
from onyx.configs.app_configs import FRESHDESK_MAX_RETRIES
from onyx.configs.app_configs import FRESHDESK_RATE_LIMIT_CAP_SECONDS
from onyx.configs.app_configs import FRESHDESK_RATE_LIMIT_WAIT_SECONDS
from onyx.configs.app_configs import FRESHDESK_RETRY_INTERVAL
from onyx.configs.app_configs import FRESHDESK_SERVER_ERROR_RETRY_DELAY
from onyx.configs.app_configs import FRESHDESK_SKIP_IMAGE_KEYWORDS
from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.configs.constants import FileOrigin
from onyx.configs.llm_configs import get_image_extraction_and_analysis_enabled
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import ImageSection
from onyx.connectors.models import TextSection
from onyx.file_processing.image_utils import store_image_and_create_section
from onyx.utils.logger import setup_logger

logger = setup_logger()

_FRESHDESK_SOLUTIONS_ID_PREFIX = "FRESHDESK_SOLUTIONS_"

FRESHDESK_BASE_URL_TEMPLATE = "https://{domain}.freshdesk.com"
FRESHDESK_ARTICLE_URL_TEMPLATE = (
    "https://{domain}.freshdesk.com/a/solutions/articles/{article_id}"
)
FRESHDESK_CATEGORIES_API_TEMPLATE = (
    "https://{domain}.freshdesk.com/api/v2/solutions/categories"
)
FRESHDESK_FOLDERS_API_TEMPLATE = (
    "https://{domain}.freshdesk.com/api/v2/solutions/categories/{category_id}/folders"
)
FRESHDESK_ARTICLES_API_TEMPLATE = (
    "https://{domain}.freshdesk.com/api/v2/solutions/folders/{folder_id}/articles"
)


def _is_invalid_image_url(url: str) -> bool:
    if not url or len(url.strip()) == 0:
        return True
    if (
        f"{FRESHDESK_ATTACHMENT_BASE_URL}{FRESHDESK_ATTACHMENT_INLINE_PATH}" in url
        and FRESHDESK_ATTACHMENT_TOKEN_PARAM not in url
    ):
        return True
    if url.endswith(FRESHDESK_ATTACHMENT_INLINE_PATH) or url.endswith(
        FRESHDESK_ATTACHMENT_PATH
    ):
        return True
    if len(url) < 20:
        return True
    return False


def _should_skip_gif(img_src: str) -> bool:
    lowered = img_src.lower()
    return lowered.endswith(".gif") or "image/gif" in lowered


def _is_freshdesk_attachment(url: str) -> bool:
    return (
        FRESHDESK_DOMAIN_SUFFIX in url
        and FRESHDESK_ATTACHMENT_BASE_URL in url
        and FRESHDESK_ATTACHMENT_PATH in url
    )


def _should_skip_image_from_text(*values: str) -> bool:
    skip_keywords = {
        keyword.strip().lower()
        for keyword in FRESHDESK_SKIP_IMAGE_KEYWORDS.split(",")
        if keyword.strip()
    }
    if not skip_keywords:
        return False

    joined_text = " ".join(value.lower() for value in values if value)
    return any(keyword in joined_text for keyword in skip_keywords)


def _is_image_too_small(image_data: bytes) -> bool:
    try:
        image = Image.open(BytesIO(image_data))
        width, height = image.size
        return width < FRESHDESK_ICON_MIN_WIDTH and height < FRESHDESK_ICON_MIN_HEIGHT
    except Exception:
        return False


def _create_metadata_from_article(article: dict, current_url: str, name: str) -> dict:
    metadata: dict[str, str | list[str]] = {
        "id": str(article.get("id", "NA")),
        "agent_id": str(article.get("agent_id", "NA")),
        "created_at": str(article.get("created_at", "NA")),
        "updated_at": str(article.get("updated_at", "NA")),
        "category_id": str(article.get("category_id", "NA")),
        "folder_id": str(article.get("folder_id", "NA")),
        "title": article.get("title", "NA"),
        "current_url": current_url,
        "connector_name": name,
    }
    tags = article.get("tags")
    if isinstance(tags, list) and tags:
        metadata["tags"] = [str(tag) for tag in tags]
    return metadata


def _create_doc_from_article(
    category: dict,
    folder: dict,
    article: dict,
    domain: str,
    name: str,
    connector: "FreshdeskSolutionsConnector",
) -> list[Document]:
    article_id = str(article["id"])
    article_title = str(article.get("title", "NA"))
    article_html_description = str(article.get("description", ""))
    description_text = str(article.get("description_text", ""))

    base_url = FRESHDESK_BASE_URL_TEMPLATE.format(domain=domain)
    article_link = FRESHDESK_ARTICLE_URL_TEMPLATE.format(
        domain=domain, article_id=article_id
    )
    soup = BeautifulSoup(article_html_description, "html.parser")

    text_parts = [
        f"Category: {category.get('name', 'NA')}",
        f"Folder: {folder.get('name', 'NA')}",
        f"Title: {article_title}",
        f"Description: {description_text}",
    ]
    tags = article.get("tags")
    if isinstance(tags, list) and tags:
        text_parts.append(f"Tags: {', '.join([str(tag) for tag in tags])}")

    metadata = _create_metadata_from_article(article, article_link, name)
    image_sections: list[ImageSection] = []
    images = soup.find_all("img")

    if images and get_image_extraction_and_analysis_enabled():
        for i, img_tag in enumerate(images):
            img_src = img_tag.get("src")
            if not isinstance(img_src, str):
                continue
            if not img_src.startswith(("http://", "https://", "data:")):
                img_src = urljoin(base_url, img_src)
            if _is_invalid_image_url(img_src) or _should_skip_gif(img_src):
                continue
            if _should_skip_image_from_text(
                str(img_tag.get("alt", "")),
                str(img_tag.get("title", "")),
                img_src,
            ):
                continue
            if not _is_freshdesk_attachment(img_src):
                continue

            try:
                response = connector._request_with_retries(
                    img_src,
                    request_delay=FRESHDESK_IMAGE_DOWNLOAD_INTERVAL,
                    timeout=FRESHDESK_IMAGE_REQUEST_TIMEOUT_SECONDS,
                    error_context="article_image",
                    use_auth=False,
                )
                content_type = response.headers.get("content-type", "").lower()
                if not content_type.startswith("image/"):
                    continue
                if _is_image_too_small(response.content):
                    continue

                filename = img_src.split("/")[-1].split("?")[0] or f"image_{i}.jpg"
                image_file_id = f"{_FRESHDESK_SOLUTIONS_ID_PREFIX}IMG_{article_id}_{i}"
                image_section, stored_file_id = store_image_and_create_section(
                    image_data=response.content,
                    file_id=image_file_id,
                    display_name=filename,
                    link=img_src,
                    media_type=content_type or "application/octet-stream",
                    file_origin=FileOrigin.CONNECTOR,
                )
                if stored_file_id:
                    image_sections.append(image_section)
            except Exception as e:
                logger.warning(
                    "Failed to process image for Freshdesk Solutions article %s (%s)",
                    article_id,
                    type(e).__name__,
                )

    if image_sections:
        metadata["contains_image_content"] = "true"
        metadata["embedded_images_count"] = str(len(image_sections))

    sections: list[TextSection | ImageSection] = [
        TextSection(link=article_link, text="\n".join(text_parts))
    ]
    sections.extend(image_sections)

    return [
        Document(
            id=_FRESHDESK_SOLUTIONS_ID_PREFIX + article_link,
            sections=sections,
            source=DocumentSource.FRESHDESK_SOLUTIONS,
            semantic_identifier=article_title,
            metadata=metadata,
            doc_updated_at=datetime.fromisoformat(
                str(article["updated_at"]).replace("Z", "+00:00")
            ),
        )
    ]


class FreshdeskSolutionsConnector(PollConnector, LoadConnector):
    name: str | None = None

    def __init__(self, batch_size: int = INDEX_BATCH_SIZE) -> None:
        self.batch_size = batch_size
        self.name = "freshdesk_solutions"
        self._article_hit_count = 0

    def _request_with_retries(
        self,
        url: str,
        *,
        params: dict[str, int | str] | None = None,
        request_delay: float = 0,
        max_retries: int | None = FRESHDESK_MAX_RETRIES,
        error_context: str = "resource",
        timeout: int | float | None = None,
        use_auth: bool = True,
    ) -> requests.Response:
        retry_count = 0
        while True:
            try:
                if request_delay:
                    time.sleep(request_delay)
                kwargs: dict[str, object] = {"params": params}
                if use_auth:
                    kwargs["auth"] = (self.api_key, self.password)
                if timeout is not None:
                    kwargs["timeout"] = timeout
                response = requests.get(url, **kwargs)
            except Exception as e:
                logger.warning(
                    "Error fetching Freshdesk %s (%s)",
                    error_context,
                    type(e).__name__,
                )
                retry_count += 1
                time.sleep(FRESHDESK_RETRY_INTERVAL)
            else:
                if response.status_code == 429:
                    retry_after = min(
                        int(
                            response.headers.get(
                                "Retry-After", str(FRESHDESK_RETRY_INTERVAL)
                            )
                        ),
                        FRESHDESK_RATE_LIMIT_CAP_SECONDS,
                    )
                    retry_count += 1
                    time.sleep(retry_after)
                elif response.status_code == 500:
                    retry_count += 1
                    time.sleep(FRESHDESK_SERVER_ERROR_RETRY_DELAY)
                else:
                    response.raise_for_status()
                    return response

            if max_retries is not None and retry_count >= max_retries:
                raise RuntimeError(
                    f"Failed to fetch Freshdesk {error_context} after {max_retries} retries"
                )

    def load_credentials(self, credentials: dict[str, str | int]) -> None:
        api_key = credentials.get("freshdesk_solution_api_key")
        domain = credentials.get("freshdesk_solution_domain")
        password = credentials.get("freshdesk_solution_password")

        if not all(isinstance(cred, str) for cred in [domain, api_key, password]):
            raise ConnectorMissingCredentialError(
                "All Freshdesk solutions credentials must be strings"
            )

        normalized_domain = str(domain).strip().lower().rstrip("/")
        if normalized_domain.startswith(("http://", "https://")):
            normalized_domain = normalized_domain.replace("http://", "").replace(
                "https://", ""
            )
        if FRESHDESK_DOMAIN_SUFFIX in normalized_domain:
            normalized_domain = normalized_domain.split(FRESHDESK_DOMAIN_SUFFIX)[0]
        normalized_domain = normalized_domain.rstrip(".")
        if not normalized_domain:
            raise ConnectorMissingCredentialError(
                "Freshdesk solutions domain cannot be empty"
            )

        self.api_key = str(api_key)
        self.domain = normalized_domain
        self.password = str(password)

    def _fetch_categories(self) -> Iterator[list[dict]]:
        if self.api_key is None or self.domain is None or self.password is None:
            raise ConnectorMissingCredentialError("freshdesk_solutions")

        url = FRESHDESK_CATEGORIES_API_TEMPLATE.format(domain=self.domain)
        response = self._request_with_retries(
            url,
            request_delay=FRESHDESK_API_REQUEST_DELAY_SECONDS,
            error_context="categories",
        )
        if response.status_code == 204:
            yield []
            return
        categories = response.json()
        if not isinstance(categories, list):
            raise RuntimeError("Unexpected Freshdesk category response format")
        yield categories

    def _fetch_folders(self, category: dict) -> Iterator[list[dict]]:
        if self.api_key is None or self.domain is None or self.password is None:
            raise ConnectorMissingCredentialError("freshdesk_solutions")

        url = FRESHDESK_FOLDERS_API_TEMPLATE.format(
            domain=self.domain, category_id=category["id"]
        )
        response = self._request_with_retries(
            url,
            request_delay=FRESHDESK_API_REQUEST_DELAY_SECONDS,
            error_context="folders",
        )
        if response.status_code == 204:
            yield []
            return
        folders = response.json()
        if not isinstance(folders, list):
            raise RuntimeError("Unexpected Freshdesk folder response format")
        yield folders

    def _fetch_articles(self, folder: dict) -> Iterator[list[dict]]:
        if self.api_key is None or self.domain is None or self.password is None:
            raise ConnectorMissingCredentialError("freshdesk_solutions")

        url = FRESHDESK_ARTICLES_API_TEMPLATE.format(
            domain=self.domain, folder_id=folder["id"]
        )
        params: dict[str, int | str] = {"per_page": 100, "page": 1}

        while True:
            if self._article_hit_count >= 100:
                time.sleep(FRESHDESK_RATE_LIMIT_WAIT_SECONDS)
                self._article_hit_count = 0

            response = self._request_with_retries(
                url,
                params=params,
                request_delay=FRESHDESK_API_REQUEST_DELAY_SECONDS,
                max_retries=FRESHDESK_MAX_RETRIES,
                error_context="articles",
            )
            if response.status_code == 204:
                yield []
                return

            articles = response.json()
            if not isinstance(articles, list):
                raise RuntimeError("Unexpected Freshdesk article response format")

            self._article_hit_count += 1
            time.sleep(FRESHDESK_ARTICLE_FETCH_DELAY_SECONDS)
            yield articles

            if len(articles) < int(params["per_page"]):
                break
            params["page"] = int(params["page"]) + 1

    def _process_articles(
        self, start: datetime | None = None
    ) -> GenerateDocumentsOutput:
        doc_batch: list[Document] = []

        all_categories: list[dict] = []
        for category_list in self._fetch_categories():
            all_categories.extend(category_list)

        for category in all_categories:
            for folder_list in self._fetch_folders(category):
                for folder in folder_list:
                    for articles in self._fetch_articles(folder):
                        for article in articles:
                            if start is not None:
                                updated_at = datetime.strptime(
                                    article["updated_at"], "%Y-%m-%dT%H:%M:%SZ"
                                ).replace(tzinfo=timezone.utc)
                                if updated_at < start:
                                    continue

                            documents = _create_doc_from_article(
                                category=category,
                                folder=folder,
                                article=article,
                                domain=self.domain,
                                name=self.name or "freshdesk_solutions",
                                connector=self,
                            )
                            doc_batch.extend(documents)

                            if len(doc_batch) >= self.batch_size:
                                yield doc_batch
                                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_articles()

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        del end
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        yield from self._process_articles(start_datetime)
