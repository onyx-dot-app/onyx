from datetime import datetime
from typing import Any
from urllib.parse import urlparse

from redminelib import Redmine
from redminelib.exceptions import ResourceAttrError

from onyx.configs.app_configs import INDEX_BATCH_SIZE
from onyx.configs.constants import DocumentSource
from onyx.connectors.cross_connector_utils.miscellaneous_utils import datetime_to_utc
from onyx.connectors.interfaces import LoadConnector, PollConnector, GenerateDocumentsOutput, SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError, Document, BasicExpertInfo, Section, TextSection

PROJECT_URL_PAT = "projects"


def extract_redmine_project(url: str) -> tuple[str, str]:
    """Sample
    http://redmine.com/projects/test-project
    base_url is http://redmine.com
    project is test-project
    """
    parsed_url = urlparse(url)
    redmine_base = parsed_url.scheme + "://" + parsed_url.netloc

    # Split the path by '/' and find the position of 'projects' to get the project name
    split_path = parsed_url.path.split("/")
    if PROJECT_URL_PAT in split_path:
        project_pos = split_path.index(PROJECT_URL_PAT)
        if len(split_path) > project_pos + 1:
            redmine_project = split_path[project_pos + 1]
        else:
            raise ValueError("No project name found in the URL")
    else:
        raise ValueError("'projects' not found in the URL")

    return redmine_base, redmine_project


class RedmineConnector(LoadConnector, PollConnector):
    def __init__(self,
                 redmine_project_url: str,
                 batch_size: int = INDEX_BATCH_SIZE):
        self.batch_size = batch_size
        self.redmine_base_url, self.redmine_project = extract_redmine_project(redmine_project_url)
        self.redmine_client: Redmine | None = None

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        if "redmine_username" in credentials and "redmine_password" in credentials:
            self.redmine_client = Redmine(
                url=self.redmine_base_url,
                username=credentials['redmine_username'],
                password=credentials['redmine_password']
            )
        else:
            raise ValueError("Authorization data is not specified")
        self.redmine_client.auth()
        return None

    def _process_issues(self, start: datetime | None = None, end: datetime | None = None) -> GenerateDocumentsOutput:
        if self.redmine_client is None:
            raise ConnectorMissingCredentialError("Redmine")

        project = self.redmine_client.project.get(self.redmine_project)
        issues = project.issues
        wiki_pages = project.wiki_pages
        doc_batch: list[Document] = []
        for wiki in wiki_pages:
            updated_at = wiki.updated_on.replace(tzinfo=None)
            if start is not None and updated_at < start:
                continue
            if end is not None and updated_at > end:
                continue
            wiki_info = self.redmine_client.wiki_page.get(wiki.internal_id, project_id=self.redmine_project)

            people = set()
            people.add(
                BasicExpertInfo(
                    display_name=wiki_info.author.name
                )
            )

            doc_batch.append(
                Document(
                    id=wiki_info.internal_id,
                    sections=[TextSection(link=wiki_info.url, text=wiki_info.text)],
                    source=DocumentSource.REDMINE,
                    semantic_identifier=wiki_info.title,
                    doc_updated_at=datetime_to_utc(updated_at),
                    title=wiki_info.title,
                    primary_owners=list(people) or None,
                    metadata={},
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        for issue in issues:
            updated_at = issue.updated_on.replace(tzinfo=None)
            if start is not None and updated_at < start:
                continue
            if end is not None and updated_at > end:
                continue
            subject = issue.subject
            link = issue.url
            semantic_rep = f"{issue.description}\n" + "\n".join(
                [f"Comment: {comment.notes}" for comment in issue.journals]
            )

            people = set()
            try:
                people.add(
                    BasicExpertInfo(
                        display_name=issue.author.name
                    )
                )

                people.add(
                    BasicExpertInfo(
                        display_name=issue.assigned_to.name
                    )
                )
            except ResourceAttrError:
                pass
            metadata_dict = self.get_metadata_from_issue(issue)

            doc_batch.append(
                Document(
                    id=link,
                    sections=[Section(link=link, text=semantic_rep)],
                    source=DocumentSource.REDMINE,
                    semantic_identifier=subject,
                    doc_updated_at=datetime_to_utc(updated_at),
                    primary_owners=list(people) or None,
                    metadata=metadata_dict,
                )
            )

            if len(doc_batch) >= self.batch_size:
                yield doc_batch
                doc_batch = []

        if doc_batch:
            yield doc_batch

    def load_from_state(self) -> GenerateDocumentsOutput:
        return self._process_issues()

    def poll_source(
            self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        start_datetime = datetime.utcfromtimestamp(start)
        end_datetime = datetime.utcfromtimestamp(end)
        return self._process_issues(start_datetime, end_datetime)

    @staticmethod
    def get_metadata_from_issue(issue: Any) -> dict:
        metadata = {}
        try:
            if issue.priority:
                metadata['priority'] = issue.priority.name
        except ResourceAttrError:
            pass
        try:
            if issue.status:
                metadata['status'] = issue.status.name
        except ResourceAttrError:
            pass
        try:
            if issue.tracker:
                metadata['tracker'] = issue.tracker.name
        except ResourceAttrError:
            pass
        try:
            if issue.category:
                metadata['category'] = issue.category.name
        except ResourceAttrError:
            pass

        return metadata


if __name__ == "__main__":
    import os

    connector = RedmineConnector(
        os.environ["REDMINE_PROJECT_URL"],
    )
    connector.load_credentials(
        {
            "redmine_username": os.environ["REDMINE_USER_USERNAME"],
            "redmine_password": os.environ["REDMINE_USER_PASSWORD"],
        }
    )
    document_batches = connector.load_from_state()
    print(next(document_batches))
