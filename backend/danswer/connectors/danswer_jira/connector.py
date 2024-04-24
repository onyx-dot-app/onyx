import os
from datetime import datetime
from datetime import timezone
from typing import Any
from urllib.parse import urlparse

from jira import JIRA
from jira.resources import Issue

from danswer.configs.app_configs import INDEX_BATCH_SIZE
from danswer.configs.app_configs import JIRA_CONNECTOR_LABELS_TO_SKIP
from danswer.configs.constants import DocumentSource
from danswer.connectors.cross_connector_utils.miscellaneous_utils import time_str_to_utc
from danswer.connectors.interfaces import GenerateDocumentsOutput
from danswer.connectors.interfaces import LoadConnector
from danswer.connectors.interfaces import PollConnector
from danswer.connectors.interfaces import SecondsSinceUnixEpoch
from danswer.connectors.models import BasicExpertInfo
from danswer.connectors.models import ConnectorMissingCredentialError
from danswer.connectors.models import Document
from danswer.connectors.models import Section
from danswer.utils.logger import setup_logger


logger = setup_logger()
PROJECT_URL_PAT = "projects"
JIRA_API_VERSION = os.environ.get("JIRA_API_VERSION") or "2"


def extract_jira_project(url: str) -> tuple[str, str]:
    parsed_url = urlparse(url)
    jira_base = parsed_url.scheme + "://" + parsed_url.netloc

    # Split the path by '/' and find the position of 'projects' to get the project name
    split_path = parsed_url.path.split("/")
    if PROJECT_URL_PAT in split_path:
        project_pos = split_path.index(PROJECT_URL_PAT)
        if len(split_path) > project_pos + 1:
            jira_project = split_path[project_pos + 1]
        else:
            raise ValueError("No project name found in the URL")
    else:
        raise ValueError("'projects' not found in the URL")

    return jira_base, jira_project


def _get_comment_strs(
    jira: Issue,
    comment_email_blacklist: tuple[str, ...] = (),
) -> list[str]:
    comment_strs = []
    for comment in jira.fields.comment.comments:
        # Can't test Jira server so can't be sure this works for everyone, wrapping in a try just
        # in case
        try:
            comment_strs.append(comment.body)
            # If this fails, we just assume it's ok to keep the comment
            if comment.author.emailAddress in comment_email_blacklist:
                comment_strs.pop()
        except Exception:
            pass
    return comment_strs


def fetch_jira_issues_batch(
    jql: str,
    start_index: int,
    jira_client: JIRA,
    batch_size: int = INDEX_BATCH_SIZE,
    comment_email_blacklist: tuple[str, ...] = (),
    labels_to_skip: set[str] | None = None,
) -> tuple[list[Document], int]:
    doc_batch = []

    batch = jira_client.search_issues(
        jql,
        startAt=start_index,
        maxResults=batch_size,
    )

    for jira in batch:
        if type(jira) != Issue:
            logger.warning(f"Found Jira object not of type Issue {jira}")
            continue

        if labels_to_skip and any(
            label in jira.fields.labels for label in labels_to_skip
        ):
            logger.info(
                f"Skipping {jira.key} because it has a label to skip. Found "
                f"labels: {jira.fields.labels}. Labels to skip: {labels_to_skip}."
            )
            continue

        comments = _get_comment_strs(jira, comment_email_blacklist)
        semantic_rep = f"{jira.fields.description}\n" + "\n".join(
            [f"Comment: {comment}" for comment in comments]
        )

        page_url = f"{jira_client.client_info()}/browse/{jira.key}"

        people = set()
        try:
            people.add(
                BasicExpertInfo(
                    display_name=jira.fields.creator.displayName,
                    email=jira.fields.creator.emailAddress,
                )
            )
        except Exception:
            # Author should exist but if not, doesn't matter
            pass

        try:
            people.add(
                BasicExpertInfo(
                    display_name=jira.fields.assignee.displayName,  # type: ignore
                    email=jira.fields.assignee.emailAddress,  # type: ignore
                )
            )
        except Exception:
            # Author should exist but if not, doesn't matter
            pass

        metadata_dict = {}
        if jira.fields.priority:
            metadata_dict["priority"] = jira.fields.priority.name
        if jira.fields.status:
            metadata_dict["status"] = jira.fields.status.name
        if jira.fields.resolution:
            metadata_dict["resolution"] = jira.fields.resolution.name
        if jira.fields.labels:
            metadata_dict["label"] = jira.fields.labels

        doc_batch.append(
            Document(
                id=page_url,
                sections=[Section(link=page_url, text=semantic_rep)],
                source=DocumentSource.JIRA,
                semantic_identifier=jira.fields.summary,
                doc_updated_at=time_str_to_utc(jira.fields.updated),
                primary_owners=list(people) or None,
                # TODO add secondary_owners (commenters) if needed
                metadata=metadata_dict,
            )
        )
    return doc_batch, len(batch)


class JiraConnector(LoadConnector, PollConnector):
    def __init__(
        self,
        jira_project_url: str,
        comment_email_blacklist: list[str] | None = None,
        batch_size: int = INDEX_BATCH_SIZE,
        # if a ticket has one of the labels specified in this list, we will just
        # skip it. This is generally used to avoid indexing extra sensitive
        # tickets.
        labels_to_skip: list[str] = JIRA_CONNECTOR_LABELS_TO_SKIP,
    ) -> None:
        self.batch_size = batch_size
        self.jira_base, self.jira_project = extract_jira_project(jira_project_url)
        self.jira_client: JIRA | None = None
        self._comment_email_blacklist = comment_email_blacklist or []

        self.labels_to_skip = set(labels_to_skip)

    @property
    def comment_email_blacklist(self) -> tuple:
        return tuple(email.strip() for email in self._comment_email_blacklist)

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        api_token = credentials["jira_api_token"]
        # if user provide an email we assume it's cloud
        if "jira_user_email" in credentials:
            email = credentials["jira_user_email"]
            self.jira_client = JIRA(
                basic_auth=(email, api_token),
                server=self.jira_base,
                options={"rest_api_version": JIRA_API_VERSION},
            )
        else:
            self.jira_client = JIRA(
                token_auth=api_token,
                server=self.jira_base,
                options={"rest_api_version": JIRA_API_VERSION},
            )
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        if self.jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        start_ind = 0
        while True:
            doc_batch, fetched_batch_size = fetch_jira_issues_batch(
                jql=f"project = {self.jira_project}",
                start_index=start_ind,
                jira_client=self.jira_client,
                batch_size=self.batch_size,
                comment_email_blacklist=self.comment_email_blacklist,
                labels_to_skip=self.labels_to_skip,
            )

            if doc_batch:
                yield doc_batch

            start_ind += fetched_batch_size
            if fetched_batch_size < self.batch_size:
                break

    def poll_source(
        self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        if self.jira_client is None:
            raise ConnectorMissingCredentialError("Jira")

        start_date_str = datetime.fromtimestamp(start, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )
        end_date_str = datetime.fromtimestamp(end, tz=timezone.utc).strftime(
            "%Y-%m-%d %H:%M"
        )

        jql = (
            f"project = {self.jira_project} AND "
            f"updated >= '{start_date_str}' AND "
            f"updated <= '{end_date_str}'"
        )

        start_ind = 0
        while True:
            doc_batch, fetched_batch_size = fetch_jira_issues_batch(
                jql=jql,
                start_index=start_ind,
                jira_client=self.jira_client,
                batch_size=self.batch_size,
                comment_email_blacklist=self.comment_email_blacklist,
                labels_to_skip=self.labels_to_skip,
            )

            if doc_batch:
                yield doc_batch

            start_ind += fetched_batch_size
            if fetched_batch_size < self.batch_size:
                break


if __name__ == "__main__":
    import os

    connector = JiraConnector(
        os.environ["JIRA_PROJECT_URL"], comment_email_blacklist=[]
    )
    connector.load_credentials(
        {
            "jira_user_email": os.environ["JIRA_USER_EMAIL"],
            "jira_api_token": os.environ["JIRA_API_TOKEN"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
