from __future__ import annotations

import datetime
from urllib.parse import urlparse
from collections.abc import Generator
from typing import Any
from typing import ClassVar

from onyx.configs.constants import DocumentSource
from onyx.connectors.interfaces import GenerateDocumentsOutput
from onyx.connectors.interfaces import LoadConnector
from onyx.connectors.interfaces import PollConnector
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import Document
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

from onyx.connectors.phabricator.phapi import get_phriction_docs, get_maniphest_tickets, UserPhidCache

logger = setup_logger()

def _ph_to_doc(doc: dict[str, Any], doc_base : str) -> Document:
    """
    Parses out the specific information from a Phab doc into the format needed for embedding.
    
    Args:
        doc: Dict with the information from Phriction.
        doc_base: URL base to use to generate a link
    
    Returns:
        A Document object with title, path, PHID, and content.
    """
    return Document(
        title=doc['title'],
        semantic_identifier=doc['title'],
        path=doc['path'],
        doc_updated_at=datetime.datetime.fromtimestamp(doc['date_modified'], tz=datetime.timezone.utc),
        id=doc['PHID'],
        sections=[TextSection(text=doc['content'], link=doc_base + doc['path'].lstrip('/'))],
        metadata={},
        source=DocumentSource.PHABRICATOR,
    )

def _maniphest_to_doc(doc: dict[str, Any], maniphest_base: str) -> Document:
    '''
    Parses out the specific information from a Maniphest ticket into the format needed for embedding.
    
    Args:
        doc: Dict with the information from Maniphest.
        doc_base: URL base to use to generate a link
    
    Returns:
        A Document object with title, path, PHID, and content.
    '''

    return Document(
        title=doc['title'],
        semantic_identifier=f"{doc['tid']} - {doc['title']}",
        path=doc['tid'],
        doc_updated_at=datetime.datetime.fromtimestamp(doc['date_modified'], tz=datetime.timezone.utc),
        id=doc['PHID'],
        sections=[TextSection(text=doc['description'], link=maniphest_base + doc['tid'])],
        metadata={},
        source=DocumentSource.PHABRICATOR
    )

class PhabricatorConnector(LoadConnector, PollConnector):
    """
    Connector for Phabricator, a suite of open-source tools for software development.
    This connector supports loading documents from Phabricator's Phriction wiki.
    """

    family: ClassVar[str] = 'phabricator'
    source: DocumentSource = DocumentSource.PHABRICATOR

    def __init__(self, api_base: str) -> None:
        self.api_token = ''
        self.user_phid_cache = UserPhidCache()
        self.api_base = api_base
        self.doc_base = urlparse(api_base)._replace(path="/w/").geturl()
        self.maniphest_base = urlparse(api_base)._replace(path="/").geturl()

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        self.api_token = credentials.get('phab_api_token', '')
        return None

    def _get_docs(self, start : SecondsSinceUnixEpoch | None = None, end : SecondsSinceUnixEpoch | None = None) -> Generator[list[Document], None, None]:
        """
        Fetches documents from the Phabricator Phriction wiki.
        
        Yields:
            Document objects containing the title, path, PHID, and content.
        """
        docs = get_phriction_docs(limit = -1, api_base=self.api_base, api_token=self.api_token, start=start, end=end, logger=logger)
        for doc in docs:
            yield [_ph_to_doc(doc, self.doc_base)]
        tickets = get_maniphest_tickets(limit = -1, api_base=self.api_base, api_token=self.api_token, user_phid_cache=self.user_phid_cache, start=start, end=end, logger=logger)
        for ticket in tickets:
            yield [_maniphest_to_doc(ticket, self.maniphest_base)]

    def load_from_state(self) -> GenerateDocumentsOutput:
        """
        Generates documents from the Phabricator Phriction wiki.
        """
        return self._get_docs()

    def poll_source(self, start: SecondsSinceUnixEpoch, end: SecondsSinceUnixEpoch) -> GenerateDocumentsOutput:
        '''
        Polls for new documents
        '''
        return self._get_docs(start, end)
    
