"""The connector check graph: each source's checks, their static metadata and
the checks each one runs after.

A source's ``checks.json`` is the source of truth for that metadata and
for the dependencies. Check classes keep only behaviour (``run``, ``applies``)
and read the rest from their node by ``check_id``. Permission-sync nodes,
which only the EE registry registers, live in a separate file under ``ee/``.

The graphs are loaded and validated once per process, on first use.
"""

from functools import cache
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from onyx.configs.constants import DocumentSource
from onyx.connectors.capabilities import CredentialCapability
from onyx.db.enums import AccessType

# backend/, the parent of the onyx/ and ee/ packages.
_BACKEND_ROOT = Path(__file__).resolve().parents[3]
_GRAPH_FILE_NAME = "checks.json"


class CheckNode(BaseModel):
    """One check's static metadata. Defaults match ``CapabilityCheck``'s."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    display_name: str
    capability: CredentialCapability = CredentialCapability.INDEXING
    required: bool = True
    requires_connector_instance: bool = True
    requires_connector_config: bool = False
    requires_fields: tuple[str, ...] = ()
    # None: the capability's default (permission-sync checks apply to the
    # permission-synced access types, other checks to all of them).
    access_types: tuple[AccessType, ...] | None = None
    timeout_seconds: float | None = None
    remediation: str | None = None
    docs_link: str | None = None
    validates_binding: bool = False
    discovery: bool = False
    fails_when_unreachable: bool = False
    # The checks this one runs after, in order: the first one that stops it
    # names the cause. One that does not apply is left out, so a node can list
    # alternatives (e.g. both token types' sign-in checks).
    depends_on: tuple[str, ...] = ()
    # The row the check shows on; None is its own id.
    row_id: str | None = None


class CheckGraphFile(BaseModel):
    """The contents of one ``checks.json``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: DocumentSource
    nodes: tuple[CheckNode, ...]


class CheckGraphNode(CheckNode):
    """A node as the check graph endpoint serves it: the check's resolved
    metadata, plus what only its code knows."""

    # The check has an ``applies(form_state)`` predicate, so whether it applies
    # to a form is known only to the server (the plan endpoint or a run).
    conditional: bool
    # A synthesized wrapper around the legacy validation blob, for a source or
    # capability without named checks.
    is_fallback: bool


class CheckGraphEdge(BaseModel):
    """``prerequisite`` must settle before ``dependent`` runs."""

    model_config = ConfigDict(frozen=True)

    prerequisite: str
    dependent: str


class CheckGraph(BaseModel):
    """A source's registered checks as a DAG, for the frontend to schedule
    from. Edges point from a prerequisite to its dependent."""

    model_config = ConfigDict(frozen=True)

    source: DocumentSource
    nodes: tuple[CheckGraphNode, ...]
    edges: tuple[CheckGraphEdge, ...]


class CheckGraphError(ValueError):
    """A check graph file is malformed: a duplicate id, a dependency on an
    unknown check, or a cycle."""


def _graph_paths(source: DocumentSource) -> list[Path]:
    return [
        _BACKEND_ROOT / "onyx" / "connectors" / source.value / _GRAPH_FILE_NAME,
        _BACKEND_ROOT
        / "ee"
        / "onyx"
        / "external_permissions"
        / source.value
        / _GRAPH_FILE_NAME,
    ]


def _validate(source: DocumentSource, nodes: list[CheckNode]) -> None:
    ids = [node.id for node in nodes]
    duplicates = sorted({check_id for check_id in ids if ids.count(check_id) > 1})
    if duplicates:
        raise CheckGraphError(
            f"{source.value}: duplicate check ids: {', '.join(duplicates)}"
        )
    known = set(ids)
    for node in nodes:
        unknown = [dep for dep in node.depends_on if dep not in known]
        if unknown:
            raise CheckGraphError(
                f"{source.value}: {node.id} depends on unknown checks: "
                + ", ".join(unknown)
            )
    # Kahn's algorithm: whatever is left once no node is ready is a cycle.
    remaining = {node.id: set(node.depends_on) for node in nodes}
    while remaining:
        ready = [check_id for check_id, deps in remaining.items() if not deps]
        if not ready:
            raise CheckGraphError(
                f"{source.value}: check dependencies form a cycle among: "
                + ", ".join(sorted(remaining))
            )
        for check_id in ready:
            del remaining[check_id]
        for deps in remaining.values():
            deps.difference_update(ready)


@cache
def load_check_graph(source: DocumentSource) -> tuple[CheckNode, ...]:
    """Every node of ``source``'s check graph: the OSS file, then the EE file,
    each when present. Empty for a source without named checks.

    Raises:
        CheckGraphError: The merged graph is malformed.
    """
    nodes: list[CheckNode] = []
    for path in _graph_paths(source):
        if not path.is_file():
            continue
        graph_file = CheckGraphFile.model_validate_json(path.read_text())
        if graph_file.source != source:
            raise CheckGraphError(
                f"{path} declares source {graph_file.source.value}, not {source.value}"
            )
        nodes.extend(graph_file.nodes)
    _validate(source, nodes)
    return tuple(nodes)


def check_node(source: DocumentSource, check_id: str) -> CheckNode:
    """The node of one check in ``source``'s check graph.

    Raises:
        CheckGraphError: The graph has no node with that id.
    """
    for node in load_check_graph(source):
        if node.id == check_id:
            return node
    raise CheckGraphError(f"{source.value} check graph has no check {check_id}")
