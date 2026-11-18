from collections.abc import Iterator

from onyx.connectors.load_all import ConnectorOutput as ConnectorOutput
from onyx.connectors.load_all import check_hierarchy_tree as check_hierarchy_tree
from onyx.connectors.load_all import (
    load_all_from_connector as load_all_from_connector,
)
from onyx.connectors.load_all import (
    set_test_staging_callback as set_test_staging_callback,
)
from onyx.connectors.models import (
    Document,
    ImageSection,
    TabularSection,
    TextSection,
)


def to_sections(
    documents: list[Document],
) -> Iterator[TextSection | ImageSection | TabularSection]:
    for doc in documents:
        for section in doc.sections:
            yield section


def to_text_sections(
    sections: Iterator[TextSection | ImageSection | TabularSection],
) -> Iterator[str]:
    for section in sections:
        if isinstance(section, TextSection):
            yield section.text
