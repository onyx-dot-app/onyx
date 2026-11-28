"""The order in which the model reads the tools: the direct tool list, the
functions and deferred namespaces of the code mode run tool's description,
and the system prompt's tool guidance. Every model family uses this order;
the family's tools fill the same slots. The order is fixed for a set of
tools, so the tool definitions stay byte-identical across steps. Chat agents
apply it; deep research agents offer their fixed tool set unchanged."""

from enum import IntEnum, auto
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from onyx.tools.interface import Tool


class ToolRank(IntEnum):
    """A tool's slot, by its role; each tool class declares its rank. Members
    are in order: code mode, internal search, the sandbox VM, the other
    built-in tools, orchestration, then integrations."""

    CODE_MODE_RUN = auto()
    CODE_MODE_WAIT = auto()
    INTERNAL_SEARCH = auto()
    SHELL = auto()
    SHELL_INPUT = auto()
    FILE_EDIT = auto()
    PUBLISHED_FILES = auto()
    # The chat's tabs in the sandbox's browser.
    BROWSER = auto()
    WEB_SEARCH = auto()
    OPEN_URL = auto()
    READ_FILE = auto()
    POSTGRES_QUERY = auto()
    PYTHON = auto()
    IMAGE_GENERATION = auto()
    MEMORY = auto()
    KNOWLEDGE_GRAPH = auto()
    SKILLS_LIST = auto()
    SKILLS_READ = auto()
    # Copies a skill's files into the sandbox: a skill operation, though it
    # runs in the VM.
    SKILLS_LOAD = auto()
    SPAWN_AGENT = auto()
    LIST_AGENTS = auto()
    INTERRUPT_AGENT = auto()
    SEND_MESSAGE = auto()
    WAIT_AGENT = auto()
    QUESTION = auto()
    # MCP, OpenAPI and custom tools.
    INTEGRATION = auto()


def tool_order(tool: "Tool") -> tuple[ToolRank, str, str]:
    """The sort key of a tool: its rank, then its namespace (such as its MCP
    server) and name, so tools of one rank have a fixed order."""
    name = tool.code_mode_function_name
    return tool.rank, name.namespace or "", name.name
