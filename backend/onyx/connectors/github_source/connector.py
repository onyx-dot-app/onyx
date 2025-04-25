import concurrent.futures
import copy
import json
import os
import re
import shutil
import time
from collections.abc import Generator
from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from datetime import timezone
from enum import Enum
from typing import Any
from typing import cast
from typing import Optional

import requests
import tree_sitter
from github import Github
from github import RateLimitExceededException
from github import Repository
from github.ContentFile import ContentFile
from github.GithubException import GithubException
from github.Issue import Issue
from github.PaginatedList import PaginatedList
from github.PullRequest import PullRequest
from github.Requester import Requester
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pydantic import BaseModel
from tree_sitter import Language
from tree_sitter import Parser
from typing_extensions import override

from onyx.configs.app_configs import GITHUB_CONNECTOR_BASE_URL
from onyx.configs.constants import DocumentSource
from onyx.connectors.exceptions import ConnectorValidationError
from onyx.connectors.exceptions import CredentialExpiredError
from onyx.connectors.exceptions import InsufficientPermissionsError
from onyx.connectors.exceptions import UnexpectedValidationError
from onyx.connectors.interfaces import CheckpointedConnector
from onyx.connectors.interfaces import CheckpointOutput
from onyx.connectors.interfaces import ConnectorCheckpoint
from onyx.connectors.interfaces import ConnectorFailure
from onyx.connectors.interfaces import SecondsSinceUnixEpoch
from onyx.connectors.models import ConnectorMissingCredentialError
from onyx.connectors.models import Document
from onyx.connectors.models import DocumentFailure
from onyx.connectors.models import Section
from onyx.connectors.models import TextSection
from onyx.utils.logger import setup_logger

# from git import Repo, GitCommandError

logger = setup_logger()

ITEMS_PER_PAGE = 100

_MAX_NUM_RATE_LIMIT_RETRIES = 5


def _sleep_after_rate_limit_exception(github_client: Github) -> None:
    sleep_time = github_client.get_rate_limit().core.reset.replace(
        tzinfo=timezone.utc
    ) - datetime.now(tz=timezone.utc)
    sleep_time += timedelta(minutes=1)  # add an extra minute just to be safe
    logger.notice(f"Ran into Github rate-limit. Sleeping {sleep_time.seconds} seconds.")
    time.sleep(sleep_time.seconds)


def _get_batch_rate_limited(
    git_objs: PaginatedList, page_num: int, github_client: Github, attempt_num: int = 0
) -> list[PullRequest | Issue]:
    if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
        raise RuntimeError(
            "Re-tried fetching batch too many times. Something is going wrong with fetching objects from Github"
        )

    try:
        objs = list(git_objs.get_page(page_num))
        # fetch all data here to disable lazy loading later
        # this is needed to capture the rate limit exception here (if one occurs)
        for obj in objs:
            if hasattr(obj, "raw_data"):
                getattr(obj, "raw_data")
        return objs
    except RateLimitExceededException:
        _sleep_after_rate_limit_exception(github_client)
        return _get_batch_rate_limited(
            git_objs, page_num, github_client, attempt_num + 1
        )


def _convert_pr_to_document(pull_request: PullRequest) -> Document:
    return Document(
        id=pull_request.html_url,
        sections=[
            TextSection(link=pull_request.html_url, text=pull_request.body or "")
        ],
        source=DocumentSource.GITHUB,
        semantic_identifier=pull_request.title,
        # updated_at is UTC time but is timezone unaware, explicitly add UTC
        # as there is logic in indexing to prevent wrong timestamped docs
        # due to local time discrepancies with UTC
        doc_updated_at=(
            pull_request.updated_at.replace(tzinfo=timezone.utc)
            if pull_request.updated_at
            else None
        ),
        metadata={
            "merged": str(pull_request.merged),
            "state": pull_request.state,
        },
    )


def _fetch_issue_comments(issue: Issue) -> str:
    comments = issue.get_comments()
    return "\nComment: ".join(comment.body for comment in comments)


def _convert_issue_to_document(issue: Issue) -> Document:
    return Document(
        id=issue.html_url,
        sections=[TextSection(link=issue.html_url, text=issue.body or "")],
        source=DocumentSource.GITHUB,
        semantic_identifier=issue.title,
        # updated_at is UTC time but is timezone unaware
        doc_updated_at=issue.updated_at.replace(tzinfo=timezone.utc),
        metadata={
            "state": issue.state,
        },
    )


class SerializedRepository(BaseModel):
    # id is part of the raw_data as well, just pulled out for convenience
    id: int
    headers: dict[str, str | int]
    raw_data: dict[str, Any]

    def to_Repository(self, requester: Requester) -> Repository.Repository:
        return Repository.Repository(
            requester, self.headers, self.raw_data, completed=True
        )


class GithubConnectorStage(Enum):
    START = "start"
    PRS = "prs"
    ISSUES = "issues"
    FILES = "files"


class GithubConnectorCheckpoint(ConnectorCheckpoint):
    stage: GithubConnectorStage
    curr_page: int

    cached_repo_ids: list[int] | None = None
    cached_repo: SerializedRepository | None = None


@dataclass
class CodeChunk:
    """Data class representing a chunk of code with metadata."""

    text: str
    file_path: str
    chunk_id: str
    repository: str
    repo_url: str
    file_type: str
    parent_class: Optional[str] = None
    parent_function: Optional[str] = None
    namespace: Optional[str] = None
    called_functions: list[str] = field(default_factory=list)
    imports: list[str] = field(default_factory=list)
    start_line: int = 0
    end_line: int = 0
    updated_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def to_document(self) -> dict[str, Any]:
        """Convert the chunk to a document for indexing."""
        return (
            Document(
                id=self.chunk_id,
                sections=[
                    Section(link=self.repo_url + self.file_path, text=self.text or "")
                ],
                source=DocumentSource.GITHUB_SOURCE,
                semantic_identifier=self.chunk_id,
                # updated_at is UTC time but is timezone unaware
                doc_updated_at=self.updated_at.replace(tzinfo=timezone.utc),
                metadata={
                    "repository": self.repository,
                    "repo_url": self.repo_url,
                    "file_path": self.file_path,
                    "file_type": self.file_type,
                    "parent_class": self.parent_class,
                    "parent_function": self.parent_function,
                    "namespace": self.namespace,
                    "called_functions": self.called_functions,
                    "imports": self.imports,
                    "start_line": self.start_line,
                    "end_line": self.end_line,
                    "source": "github",
                },
            ),
        )
        # return {
        #     "id": self.chunk_id,
        #     "text": self.text,
        #     "metadata": {
        #         "repository": self.repository,
        #         "repo_url": self.repo_url,
        #         "file_path": self.file_path,
        #         "file_type": self.file_type,
        #         "parent_class": self.parent_class,
        #         "parent_function": self.parent_function,
        #         "namespace": self.namespace,
        #         "called_functions": self.called_functions,
        #         "imports": self.imports,
        #         "start_line": self.start_line,
        #         "end_line": self.end_line,
        #         "source": "github"
        #     }
        # }


class TreeSitterChunker:
    """Handle code parsing using tree-sitter for better code understanding."""

    # Language file paths - these need to be compiled and available
    LANGUAGE_LIBS = {
        ".py": "tree-sitter-python",
        ".js": "tree-sitter-javascript",
        ".ts": "tree-sitter-typescript",
        ".tsx": "tree-sitter-typescript",
        ".java": "tree-sitter-java",
        ".c": "tree-sitter-c",
        ".cpp": "tree-sitter-cpp",
        ".go": "tree-sitter-go",
        ".rb": "tree-sitter-ruby",
        ".php": "tree-sitter-php",
        ".cs": "tree-sitter-c-sharp",
        ".rs": "tree-sitter-rust",
    }

    def __init__(self, language_dir: str = "./tree-sitter-langs"):
        """
        Initialize the TreeSitterChunker.

        Args:
            language_dir: Directory containing compiled tree-sitter language libraries
        """
        self.language_dir = language_dir
        self.parsers = {}
        self._init_parsers()

    def _init_parsers(self):
        """Initialize parsers for supported languages."""
        if not os.path.exists(self.language_dir):
            logger.warning(
                f"Language directory {self.language_dir} not found. Tree-sitter parsing will be limited."
            )
            return

        try:
            for ext, lib_name in self.LANGUAGE_LIBS.items():
                lib_path = os.path.join(self.language_dir, f"{lib_name}.so")
                if os.path.exists(lib_path):
                    lang = Language(lib_path, ext[1:])  # Remove dot from extension
                    parser = Parser()
                    parser.set_language(lang)
                    self.parsers[ext] = parser
                    logger.info(f"Loaded Tree-sitter parser for {ext}")
        except Exception as e:
            logger.error(f"Error initializing tree-sitter parsers: {e}")

    def has_parser(self, file_ext: str) -> bool:
        """Check if a parser exists for the given file extension."""
        return file_ext in self.parsers

    def extract_metadata(self, code: str, file_path: str) -> dict[str, Any]:
        """
        Extract metadata from code using tree-sitter.

        Args:
            code: Source code
            file_path: Path to the file

        Returns:
            dictionary of extracted metadata
        """
        _, ext = os.path.splitext(file_path)

        metadata = {
            "imports": [],
            "classes": [],
            "functions": [],
            "called_functions": [],
        }

        if ext not in self.parsers:
            return metadata

        try:
            parser = self.parsers[ext]
            tree = parser.parse(bytes(code, "utf8"))
            root_node = tree.root_node

            # Extract imports, classes, functions based on language
            if ext == ".py":
                metadata = self._extract_python_metadata(root_node)
            elif ext in (".js", ".ts", ".tsx"):
                metadata = self._extract_js_ts_metadata(root_node)
            elif ext in (".java"):
                metadata = self._extract_java_metadata(root_node)
            elif ext in (".cs"):
                metadata = self._extract_csharp_metadata(root_node)
            # Add more language-specific extractors as needed

        except Exception as e:
            logger.warning(f"Error extracting metadata from {file_path}: {e}")

        return metadata

    def _extract_python_metadata(self, root_node) -> dict[str, Any]:
        """Extract metadata from Python code."""
        metadata = {
            "imports": [],
            "classes": [],
            "functions": [],
            "called_functions": [],
        }

        # Simple query for imports
        import_query = """
        (import_statement) @import
        (import_from_statement) @import_from
        """

        # Query for classes and methods
        class_query = """
        (class_definition
          name: (identifier) @class_name) @class
        """

        function_query = """
        (function_definition
          name: (identifier) @function_name) @function
        """

        # Query for function calls
        call_query = """
        (call
          function: (identifier) @function_call)
        """

        try:
            # Parse imports
            query = tree_sitter.Query(root_node.language, import_query)
            captures = query.captures(root_node)
            for _, node in captures:
                metadata["imports"].append(node.text.decode("utf8"))

            # Parse classes
            query = tree_sitter.Query(root_node.language, class_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "class_name":
                    metadata["classes"].append(node.text.decode("utf8"))

            # Parse functions
            query = tree_sitter.Query(root_node.language, function_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "function_name":
                    metadata["functions"].append(node.text.decode("utf8"))

            # Parse function calls
            query = tree_sitter.Query(root_node.language, call_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "function_call":
                    func_name = node.text.decode("utf8")
                    if func_name not in metadata["called_functions"]:
                        metadata["called_functions"].append(func_name)

        except Exception as e:
            logger.warning(f"Error in Python metadata extraction: {e}")

        return metadata

    def _extract_js_ts_metadata(self, root_node) -> dict[str, Any]:
        """Extract metadata from JavaScript/TypeScript code."""
        metadata = {
            "imports": [],
            "classes": [],
            "functions": [],
            "called_functions": [],
        }

        # Simple query for imports
        import_query = """
        (import_statement) @import
        (import_clause) @import_clause
        """

        # Query for classes and methods
        class_query = """
        (class_declaration
          name: (identifier) @class_name) @class
        """

        function_query = """
        (function_declaration
          name: (identifier) @function_name) @function
        (method_definition
          name: (property_identifier) @method_name) @method
        """

        # Query for function calls
        call_query = """
        (call_expression
          function: (identifier) @function_call)
        """

        try:
            # Parse imports
            query = tree_sitter.Query(root_node.language, import_query)
            captures = query.captures(root_node)
            for _, node in captures:
                metadata["imports"].append(node.text.decode("utf8"))

            # Parse classes
            query = tree_sitter.Query(root_node.language, class_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "class_name":
                    metadata["classes"].append(node.text.decode("utf8"))

            # Parse functions
            query = tree_sitter.Query(root_node.language, function_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name in ("function_name", "method_name"):
                    metadata["functions"].append(node.text.decode("utf8"))

            # Parse function calls
            query = tree_sitter.Query(root_node.language, call_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "function_call":
                    func_name = node.text.decode("utf8")
                    if func_name not in metadata["called_functions"]:
                        metadata["called_functions"].append(func_name)

        except Exception as e:
            logger.warning(f"Error in JS/TS metadata extraction: {e}")

        return metadata

    def _extract_csharp_metadata(self, root_node) -> dict[str, Any]:
        """Extract metadata from C# code."""
        metadata = {
            "imports": [],
            "classes": [],
            "functions": [],
            "called_functions": [],
        }

        # Query for using statements (imports in C#)
        import_query = """
        (using_directive
        name: (qualified_name) @namespace) @using
        """

        # Query for classes
        class_query = """
        (class_declaration
        name: (identifier) @class_name) @class
        """

        # Query for interfaces
        interface_query = """
        (interface_declaration
        name: (identifier) @interface_name) @interface
        """

        # Query for methods
        method_query = """
        (method_declaration
        name: (identifier) @method_name) @method
        """

        # Query for function calls
        call_query = """
        (invocation_expression
        expression: (member_access_expression
            name: (identifier) @function_call))
        (invocation_expression
        expression: (identifier) @function_call)
        """

        # Query for namespaces
        namespace_query = """
        (namespace_declaration
        name: (qualified_name) @namespace_name) @namespace
        """

        try:
            # Parse imports (using statements)
            query = tree_sitter.Query(root_node.language, import_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "namespace":
                    metadata["imports"].append(f"using {node.text.decode('utf8')};")

            # Parse namespaces
            query = tree_sitter.Query(root_node.language, namespace_query)
            captures = query.captures(root_node)
            namespace_names = []
            for name, node in captures:
                if name == "namespace_name":
                    namespace_names.append(node.text.decode("utf8"))
            if namespace_names:
                metadata["namespace"] = namespace_names[0]

            # Parse classes
            query = tree_sitter.Query(root_node.language, class_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "class_name":
                    metadata["classes"].append(node.text.decode("utf8"))

            # Parse interfaces (also adding to classes list for simplicity)
            query = tree_sitter.Query(root_node.language, interface_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "interface_name":
                    interface_name = node.text.decode("utf8")
                    metadata["classes"].append(interface_name)

            # Parse methods
            query = tree_sitter.Query(root_node.language, method_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "method_name":
                    metadata["functions"].append(node.text.decode("utf8"))

            # Parse function calls
            query = tree_sitter.Query(root_node.language, call_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "function_call":
                    func_name = node.text.decode("utf8")
                    if func_name not in metadata["called_functions"]:
                        metadata["called_functions"].append(func_name)

        except Exception as e:
            logger.warning(f"Error in C# metadata extraction: {e}")

        return metadata

    def _extract_java_metadata(self, root_node) -> dict[str, Any]:
        """Extract metadata from Java code."""
        metadata = {
            "imports": [],
            "classes": [],
            "functions": [],
            "called_functions": [],
        }

        # Simple query for imports
        import_query = """
        (import_declaration) @import
        """

        # Query for classes and methods
        class_query = """
        (class_declaration
          name: (identifier) @class_name) @class
        """

        function_query = """
        (method_declaration
          name: (identifier) @method_name) @method
        """

        # Query for function calls
        call_query = """
        (method_invocation
          name: (identifier) @function_call)
        """

        try:
            # Parse imports
            query = tree_sitter.Query(root_node.language, import_query)
            captures = query.captures(root_node)
            for _, node in captures:
                metadata["imports"].append(node.text.decode("utf8"))

            # Parse classes
            query = tree_sitter.Query(root_node.language, class_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "class_name":
                    metadata["classes"].append(node.text.decode("utf8"))

            # Parse functions
            query = tree_sitter.Query(root_node.language, function_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "method_name":
                    metadata["functions"].append(node.text.decode("utf8"))

            # Parse function calls
            query = tree_sitter.Query(root_node.language, call_query)
            captures = query.captures(root_node)
            for name, node in captures:
                if name == "function_call":
                    func_name = node.text.decode("utf8")
                    if func_name not in metadata["called_functions"]:
                        metadata["called_functions"].append(func_name)

        except Exception as e:
            logger.warning(f"Error in Java metadata extraction: {e}")

        return metadata


class RecursiveCodeChunker:
    """
    Handles the recursive code chunking process according to the specified strategy.
    """

    def __init__(
        self,
        chunk_size: int = 1000,
        chunk_overlap: int = 100,
        tree_sitter_chunker: Optional[TreeSitterChunker] = None,
    ):
        """
        Initialize the RecursiveCodeChunker.

        Args:
            chunk_size: Size of chunks in characters (default: 1000)
            chunk_overlap: Overlap between chunks in characters (default: 100)
            tree_sitter_chunker: Optional TreeSitterChunker for enhanced parsing
        """
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.tree_sitter_chunker = tree_sitter_chunker or TreeSitterChunker()

        # Initialize language-specific splitters
        self.splitters = self._init_splitters()

    def _init_splitters(self) -> dict[str, RecursiveCharacterTextSplitter]:
        """Initialize language-specific text splitters."""
        splitters = {}

        # Python splitter
        splitters[".py"] = RecursiveCharacterTextSplitter.from_language(
            language="python",
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        # JavaScript splitter
        splitters[".js"] = RecursiveCharacterTextSplitter.from_language(
            language="js", chunk_size=self.chunk_size, chunk_overlap=self.chunk_overlap
        )

        # TypeScript splitter
        splitters[".ts"] = RecursiveCharacterTextSplitter.from_language(
            language="js",  # Use JS splitter for TS
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        # Java splitter
        splitters[".java"] = RecursiveCharacterTextSplitter.from_language(
            language="java",
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        # HTML splitter
        splitters[".html"] = RecursiveCharacterTextSplitter.from_language(
            language="html",
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        # CSS splitter
        splitters[".css"] = RecursiveCharacterTextSplitter.from_language(
            language="html",  # Use HTML for CSS
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
        )

        # Default text splitter
        splitters["default"] = RecursiveCharacterTextSplitter(
            chunk_size=self.chunk_size,
            chunk_overlap=self.chunk_overlap,
            separators=["\n\n", "\n", " ", ""],
        )

        return splitters

    def get_splitter_for_file(self, file_path: str) -> RecursiveCharacterTextSplitter:
        """Get the appropriate splitter for a file based on its extension."""
        _, ext = os.path.splitext(file_path)
        return self.splitters.get(ext.lower(), self.splitters["default"])

    def chunk_content(self, content: ContentFile) -> list[CodeChunk]:
        """
        Chunk a file recursively using the appropriate splitter.

        Args:
            content: Content of the file

        Returns:
            list of CodeChunk objects
        """
        file_path = content.path
        _, ext = os.path.splitext(file_path)
        file_type = ext.lstrip(".")
        splitter = self.get_splitter_for_file(file_path)

        # Extract code metadata if possible
        namespace = None
        parent_class = None
        called_functions = []
        imports = []

        if self.tree_sitter_chunker.has_parser(ext):
            try:
                file_content = content.decoded_content.decode("utf-8")
                code_metadata = self.tree_sitter_chunker.extract_metadata(
                    file_content, file_path
                )
                imports = code_metadata.get("imports", [])
                classes = code_metadata.get("classes", [])
                parent_class = classes[0] if classes else None
                called_functions = code_metadata.get("called_functions", [])

                # Try to extract namespace from imports or file structure
                if imports:
                    # Simple heuristic: use the first import's package as namespace
                    first_import = imports[0]
                    match = re.search(r"import\s+([a-zA-Z0-9_.]+)", first_import)
                    if match:
                        namespace = match.group(1).split(".")[0]

                if not namespace:
                    # Use directory structure for namespace
                    dir_parts = os.path.dirname(file_path).split(os.path.sep)
                    if len(dir_parts) > 1 and dir_parts[-1]:
                        namespace = dir_parts[-1]
                    elif len(dir_parts) > 2:
                        namespace = dir_parts[-2]
            except Exception as e:
                logger.warning(f"Error extracting metadata from {file_path}: {e}")

        # Chunk the text
        chunks = []
        try:
            # Split the text into chunks
            text_chunks = splitter.split_text(file_content)

            # Create CodeChunk objects
            for i, chunk_text in enumerate(text_chunks):
                # Create a unique chunk ID
                chunk_id = f"{content.repository.full_name}:{file_path}:{i}"

                # Extract line numbers
                start_line = (
                    file_content.count(
                        "\n", 0, file_content.find(chunk_text.strip()[:50])
                    )
                    + 1
                )
                end_line = start_line + chunk_text.count("\n")

                # Create chunk
                chunk = CodeChunk(
                    text=chunk_text,
                    file_path=file_path,
                    chunk_id=chunk_id,
                    repository=content.repository.name,
                    repo_url=content.repository.url,
                    file_type=file_type,
                    parent_class=parent_class,
                    namespace=namespace,
                    called_functions=called_functions,
                    imports=imports,
                    start_line=start_line,
                    end_line=end_line,
                )
                chunks.append(chunk)

        except Exception as e:
            logger.error(f"Error chunking file {file_path}: {e}")
            # If chunking fails, create a single chunk with the entire file
            chunk_id = f"{content.repository.full_name}:{file_path}:0"
            chunk = CodeChunk(
                text=file_content,
                file_path=file_path,
                chunk_id=chunk_id,
                repository=content.repository.name,
                repo_url=content.repository.url,
                file_type=file_type,
                parent_class=parent_class,
                namespace=namespace,
                called_functions=called_functions,
                imports=imports,
                start_line=1,
                end_line=file_content.count("\n") + 1,
            )
            chunks.append(chunk)

        return chunks

    def chunk_file(
        self, file_path: str, file_content: str, repo_name: str, repo_url: str
    ) -> list[CodeChunk]:
        """
        Chunk a file recursively using the appropriate splitter.

        Args:
            file_path: Path to the file
            file_content: Content of the file
            repo_name: Name of the repository
            repo_url: URL of the repository

        Returns:
            list of CodeChunk objects
        """
        _, ext = os.path.splitext(file_path)
        file_type = ext.lstrip(".")
        splitter = self.get_splitter_for_file(file_path)

        # Extract code metadata if possible
        namespace = None
        parent_class = None
        called_functions = []
        imports = []

        if self.tree_sitter_chunker.has_parser(ext):
            try:
                code_metadata = self.tree_sitter_chunker.extract_metadata(
                    file_content, file_path
                )
                imports = code_metadata.get("imports", [])
                classes = code_metadata.get("classes", [])
                parent_class = classes[0] if classes else None
                called_functions = code_metadata.get("called_functions", [])

                # Try to extract namespace from imports or file structure
                if imports:
                    # Simple heuristic: use the first import's package as namespace
                    first_import = imports[0]
                    match = re.search(r"import\s+([a-zA-Z0-9_.]+)", first_import)
                    if match:
                        namespace = match.group(1).split(".")[0]

                if not namespace:
                    # Use directory structure for namespace
                    dir_parts = os.path.dirname(file_path).split(os.path.sep)
                    if len(dir_parts) > 1 and dir_parts[-1]:
                        namespace = dir_parts[-1]
                    elif len(dir_parts) > 2:
                        namespace = dir_parts[-2]
            except Exception as e:
                logger.warning(f"Error extracting metadata from {file_path}: {e}")

        # Chunk the text
        chunks = []
        try:
            # Split the text into chunks
            text_chunks = splitter.split_text(file_content)

            # Create CodeChunk objects
            for i, chunk_text in enumerate(text_chunks):
                # Create a unique chunk ID
                chunk_id = f"{repo_name}:{file_path}:{i}"

                # Extract line numbers
                start_line = (
                    file_content.count(
                        "\n", 0, file_content.find(chunk_text.strip()[:50])
                    )
                    + 1
                )
                end_line = start_line + chunk_text.count("\n")

                # Create chunk
                chunk = CodeChunk(
                    text=chunk_text,
                    file_path=file_path,
                    chunk_id=chunk_id,
                    repository=repo_name,
                    repo_url=repo_url,
                    file_type=file_type,
                    parent_class=parent_class,
                    namespace=namespace,
                    called_functions=called_functions,
                    imports=imports,
                    start_line=start_line,
                    end_line=end_line,
                )
                chunks.append(chunk)

        except Exception as e:
            logger.error(f"Error chunking file {file_path}: {e}")
            # If chunking fails, create a single chunk with the entire file
            chunk_id = f"{repo_name}:{file_path}:0"
            chunk = CodeChunk(
                text=file_content,
                file_path=file_path,
                chunk_id=chunk_id,
                repository=repo_name,
                repo_url=repo_url,
                file_type=file_type,
                parent_class=parent_class,
                namespace=namespace,
                called_functions=called_functions,
                imports=imports,
                start_line=1,
                end_line=file_content.count("\n") + 1,
            )
            chunks.append(chunk)

        return chunks


class GithubSourceConnector(CheckpointedConnector[GithubConnectorCheckpoint]):
    def __init__(
        self,
        repo_owner: str,
        repositories: str | None = None,
        state_filter: str = "all",
        include_prs: bool = True,
        include_issues: bool = False,
        include_files: bool = False,  # New flag to include source files,
        chunk_size: int = 1000,
        chunk_overlap: int = 150,
        max_workers: int = 5,
        excluded_extensions: Optional[list[str]] = None,
        excluded_directories: Optional[list[str]] = None,
    ) -> None:
        """
        Initialize the Onyx GitHub Connector.

        Args:
            repo_owner (str): The owner of the GitHub repository.
            repo_name (str): The name of the GitHub repository.
            state_filter (str): The filter for the state of issues and pull requests. Defaults to "all".
            include_prs (bool): Whether to include pull requests in the processing. Defaults to True.
            include_issues (bool): Whether to include issues in the processing. Defaults to False.
            include_files (bool): Whether to include source files in the processing. Defaults to False.
            chunk_size (int): Size of chunks in characters for processing source files. Defaults to 1000.
            chunk_overlap (int): Overlap between chunks in characters for processing source files. Defaults to 150.
            max_workers (int): Maximum number of concurrent workers for processing. Defaults to 5.
            excluded_extensions (Optional[list[str]]): list of file extensions to exclude. Defaults to common
            binary and media file types.
            excluded_directories (Optional[list[str]]): list of directory names to exclude.
            Defaults to common ignored directories.
        """
        self.repo_owner = repo_owner
        self.repositories = repositories
        self.state_filter = state_filter
        self.include_prs = include_prs
        self.include_issues = include_issues
        self.include_files = include_files  # Initialize the new flag
        self.github_client: Github | None = None
        self.excluded_extensions = excluded_extensions or [
            ".jpg",
            ".png",
            ".gif",
            ".mp4",
            ".mp3",
            ".zip",
            ".tar",
            ".gz",
            ".pdf",
        ]
        self.excluded_directories = excluded_directories or [
            ".git",
            "node_modules",
            "__pycache__",
            "venv",
            ".env",
            "dist",
            "build",
        ]
        self.max_workers = max_workers

        # Initialize chunker
        tree_sitter_chunker = TreeSitterChunker()
        self.code_chunker = RecursiveCodeChunker(
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
            tree_sitter_chunker=tree_sitter_chunker,
        )

    def clone_repository(self, repo_url: str, branch: str = "main") -> str:
        """
        Clone a GitHub repository to a temporary directory.

        Args:
            repo_url: URL of the GitHub repository
            branch: Branch name to clone (default: main)

        Returns:
            Path to the cloned repository
        """
        logger.info("#######clone_repository commented out########")
        # temp_dir = tempfile.mkdtemp()
        # logger.info(f"Cloning repository {repo_url} to {temp_dir}")

        # clone_url = repo_url
        # if self.github_token and 'github.com' in repo_url:
        #     # Insert token for authentication if it's a GitHub repo
        #     if repo_url.startswith('https://'):
        #         clone_url = repo_url.replace('https://', f'https://{self.github_token}@')

        # try:
        #     Repo.clone_from(clone_url, temp_dir, branch=branch)
        #     logger.info(f"Successfully cloned repository to {temp_dir}")
        #     return temp_dir
        # except GitCommandError as e:
        #     logger.error(f"Failed to clone repository: {e}")
        #     shutil.rmtree(temp_dir, ignore_errors=True)
        #     raise

    def should_process_file(self, file_path: str) -> bool:
        """
        Determine if a file should be processed based on exclusion rules.

        Args:
            file_path: Path to the file

        Returns:
            Boolean indicating if the file should be processed
        """
        # Check file extension
        _, ext = os.path.splitext(file_path)
        if ext.lower() in self.excluded_extensions:
            return False

        # Check if file is in excluded directory
        parts = file_path.split(os.path.sep)
        for part in parts:
            if part in self.excluded_directories:
                return False

        return True

    def read_file_content(self, file_path: str) -> Optional[str]:
        """
        Read content of a file, handling encoding issues.

        Args:
            file_path: Path to the file

        Returns:
            File content as string or None if file can't be read
        """
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                # Try with a different encoding
                with open(file_path, "r", encoding="latin-1") as f:
                    return f.read()
            except Exception as e:
                logger.warning(f"Failed to read file {file_path}: {e}")
                return None
        except Exception as e:
            logger.warning(f"Failed to read file {file_path}: {e}")
            return None

    def index_chunk(self, chunk: CodeChunk) -> bool:
        """
        Index a single code chunk into Onyx.

        Args:
            chunk: CodeChunk object to index

        Returns:
            Boolean indicating if indexing was successful
        """
        document = chunk.to_document()

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.onyx_api_key}",
        }

        try:
            url = f"{self.onyx_api_url}/indexes/{self.index_name}/documents"
            response = requests.post(url, headers=headers, json=document)

            if response.status_code in (200, 201):
                logger.debug(f"Successfully indexed {chunk.chunk_id}")
                return True
            else:
                logger.error(
                    f"Failed to index {chunk.chunk_id}: {response.status_code} - {response.text}"
                )
                return False
        except Exception as e:
            logger.error(f"Exception during indexing of {chunk.chunk_id}: {e}")
            return False

    def index_chunks_batch(self, chunks: list[CodeChunk]) -> tuple[int, int]:
        """
        Index a batch of code chunks into Onyx.

        Args:
            chunks: list of CodeChunk objects to index

        Returns:
            Tuple of (chunks indexed, failures)
        """
        if not chunks:
            return 0, 0

        documents = [chunk.to_document() for chunk in chunks]

        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.onyx_api_key}",
        }

        try:
            url = f"{self.onyx_api_url}/indexes/{self.index_name}/documents/batch"
            response = requests.post(url, headers=headers, json=documents)

            if response.status_code in (200, 201):
                logger.info(f"Successfully indexed batch of {len(chunks)} chunks")
                return len(chunks), 0
            else:
                logger.error(
                    f"Failed to index batch: {response.status_code} - {response.text}"
                )
                return 0, len(chunks)
        except Exception as e:
            logger.error(f"Exception during batch indexing: {e}")
            return 0, len(chunks)

    def process_content(self, content: ContentFile) -> dict[str, Any]:
        """
        Process a single file and index its chunks.

        Args:
            file_path: Path to the file
            repo_name: Name of the repository
            repo_url: URL of the repository

        Returns:
            Statistics about the processing
        """
        file_path = content.path
        stats = {
            "file": os.path.basename(file_path),
            "chunks_created": 0,
            "chunks_indexed": 0,
            "errors": 0,
        }

        # Chunk the file
        chunks = self.code_chunker.chunk_content(content)
        stats["chunks_created"] = len(chunks)

        # Index the chunks
        indexed, failures = self.index_chunks_batch(chunks)
        stats["chunks_indexed"] = indexed
        stats["errors"] = failures
        stats["status"] = "success" if failures == 0 else "partial_failure"

        return stats

    def process_file(
        self, file_path: str, repo_name: str, repo_url: str
    ) -> dict[str, Any]:
        """
        Process a single file and index its chunks.

        Args:
            file_path: Path to the file
            repo_name: Name of the repository
            repo_url: URL of the repository

        Returns:
            Statistics about the processing
        """
        stats = {
            "file": os.path.basename(file_path),
            "chunks_created": 0,
            "chunks_indexed": 0,
            "errors": 0,
        }

        if not self.should_process_file(file_path):
            stats["status"] = "skipped"
            return stats

        content = self.read_file_content(file_path)
        if content is None:
            stats["status"] = "error"
            stats["errors"] = 1
            return stats

        # Skip empty files
        if not content.strip():
            stats["status"] = "empty"
            return stats

        # Chunk the file
        chunks = self.code_chunker.chunk_file(file_path, content, repo_name, repo_url)
        stats["chunks_created"] = len(chunks)

        # Index the chunks
        indexed, failures = self.index_chunks_batch(chunks)
        stats["chunks_indexed"] = indexed
        stats["errors"] = failures
        stats["status"] = "success" if failures == 0 else "partial_failure"

        return stats

    def process_directory(
        self, dir_path: str, repo_name: str, repo_url: str
    ) -> dict[str, Any]:
        """
        Process a directory recursively and index all valid files.

        Args:
            dir_path: Path to the directory
            repo_name: Name of the repository
            repo_url: URL of the repository

        Returns:
            Statistics about the processing
        """
        stats = {
            "files_processed": 0,
            "files_skipped": 0,
            "chunks_created": 0,
            "chunks_indexed": 0,
            "errors": 0,
            "file_stats": {},
        }

        file_paths = []

        # Collect all files
        for root, dirs, files in os.walk(dir_path):
            # Filter out excluded directories
            for excluded_dir in self.excluded_directories:
                if excluded_dir in dirs:
                    dirs.remove(excluded_dir)

            for file in files:
                file_path = os.path.join(root, file)
                if self.should_process_file(file_path):
                    file_paths.append(file_path)
                else:
                    stats["files_skipped"] += 1

        logger.info(f"Found {len(file_paths)} files to process in {repo_name}")

        # Process files in parallel
        with concurrent.futures.ThreadPoolExecutor(
            max_workers=self.max_workers
        ) as executor:
            future_to_file = {
                executor.submit(
                    self.process_file, file_path, repo_name, repo_url
                ): file_path
                for file_path in file_paths
            }

            for future in concurrent.futures.as_completed(future_to_file):
                file_path = future_to_file[future]
                try:
                    file_stats = future.result()
                    stats["files_processed"] += 1
                    stats["chunks_created"] += file_stats["chunks_created"]
                    stats["chunks_indexed"] += file_stats["chunks_indexed"]
                    stats["errors"] += file_stats["errors"]

                    # Store individual file stats
                    rel_path = os.path.relpath(file_path, dir_path)
                    stats["file_stats"][rel_path] = file_stats

                    if stats["files_processed"] % 50 == 0:
                        logger.info(
                            f"Processed {stats['files_processed']} files so far..."
                        )

                except Exception as e:
                    logger.error(f"Error processing file {file_path}: {e}")
                    stats["errors"] += 1
                    rel_path = os.path.relpath(file_path, dir_path)
                    stats["file_stats"][rel_path] = {
                        "status": "error",
                        "errors": 1,
                        "chunks_created": 0,
                        "chunks_indexed": 0,
                    }

        return stats

    def ingest_repository(self, repo_url: str, branch: str = "main") -> dict[str, Any]:
        """
        Ingest a GitHub repository into the Onyx index.

        Args:
            repo_url: URL of the GitHub repository
            branch: Branch name to ingest (default: main)

        Returns:
            Statistics about the ingestion process
        """
        # Extract repo name from URL
        repo_name = repo_url.rstrip("/").split("/")[-1]
        if repo_name.endswith(".git"):
            repo_name = repo_name[:-4]

        # Clone the repository
        temp_dir = None
        try:
            temp_dir = self.clone_repository(repo_url, branch)

            # Process the repository
            stats = self.process_directory(temp_dir, repo_name, repo_url)
            stats["repository"] = repo_name
            stats["branch"] = branch

            logger.info(
                f"""Repository {repo_name} processing completed:
                {json.dumps({k: v for k, v in stats.items() if k != 'file_stats'})}"""
            )
            return stats

        finally:
            # Clean up temporary directory
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)
                logger.info(f"Cleaned up temporary directory {temp_dir}")

    def ingest_repositories(
        self, repo_list: list[dict[str, str]]
    ) -> list[dict[str, Any]]:
        """
        Ingest multiple GitHub repositories into the Onyx index.

        Args:
            repo_list: list of dictionaries with 'url' and optional 'branch' keys

        Returns:
            list of statistics for each repository
        """
        results = []

        for repo_info in repo_list:
            repo_url = repo_info["url"]
            branch = repo_info.get("branch", "main")

            try:
                stats = self.ingest_repository(repo_url, branch)
                results.append(stats)
            except Exception as e:
                logger.error(f"Failed to ingest repository {repo_url}: {e}")
                results.append(
                    {
                        "repository": repo_url.rstrip("/").split("/")[-1],
                        "branch": branch,
                        "error": str(e),
                        "status": "failed",
                    }
                )

        return results

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        # defaults to 30 items per page, can be set to as high as 100
        self.github_client = (
            Github(
                credentials["github_access_token"],
                base_url=GITHUB_CONNECTOR_BASE_URL,
                per_page=ITEMS_PER_PAGE,
            )
            if GITHUB_CONNECTOR_BASE_URL
            else Github(credentials["github_access_token"], per_page=ITEMS_PER_PAGE)
        )
        return None

    def _get_github_repo(
        self, github_client: Github, attempt_num: int = 0
    ) -> Repository.Repository:
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repo too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            return github_client.get_repo(f"{self.repo_owner}/{self.repositories}")
        except RateLimitExceededException:
            _sleep_after_rate_limit_exception(github_client)
            return self._get_github_repo(github_client, attempt_num + 1)

    def _get_github_repos(
        self, github_client: Github, attempt_num: int = 0
    ) -> list[Repository.Repository]:
        """Get specific repositories based on comma-separated repo_name string."""
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repos too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            repos = []
            # Split repo_name by comma and strip whitespace
            repo_names = [
                name.strip() for name in (cast(str, self.repositories)).split(",")
            ]

            for repo_name in repo_names:
                if repo_name:  # Skip empty strings
                    try:
                        repo = github_client.get_repo(f"{self.repo_owner}/{repo_name}")
                        repos.append(repo)
                    except GithubException as e:
                        logger.warning(
                            f"Could not fetch repo {self.repo_owner}/{repo_name}: {e}"
                        )

            return repos
        except RateLimitExceededException:
            _sleep_after_rate_limit_exception(github_client)
            return self._get_github_repos(github_client, attempt_num + 1)

    def _get_all_repos(
        self, github_client: Github, attempt_num: int = 0
    ) -> list[Repository.Repository]:
        if attempt_num > _MAX_NUM_RATE_LIMIT_RETRIES:
            raise RuntimeError(
                "Re-tried fetching repos too many times. Something is going wrong with fetching objects from Github"
            )

        try:
            # Try to get organization first
            try:
                org = github_client.get_organization(self.repo_owner)
                return list(org.get_repos())
            except GithubException:
                # If not an org, try as a user
                user = github_client.get_user(self.repo_owner)
                return list(user.get_repos())
        except RateLimitExceededException:
            _sleep_after_rate_limit_exception(github_client)
            return self._get_all_repos(github_client, attempt_num + 1)

    def _fetch_from_github(
        self,
        checkpoint: GithubConnectorCheckpoint,
        start: datetime | None = None,
        end: datetime | None = None,
    ) -> Generator[Document | ConnectorFailure, None, GithubConnectorCheckpoint]:
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub")

        checkpoint = copy.deepcopy(checkpoint)

        # First run of the connector, fetch all repos and store in checkpoint
        if checkpoint.cached_repo_ids is None:
            repos = []
            if self.repositories:
                if "," in self.repositories:
                    # Multiple repositories specified
                    repos = self._get_github_repos(self.github_client)
                else:
                    # Single repository (backward compatibility)
                    repos = [self._get_github_repo(self.github_client)]
            else:
                # All repositories
                repos = self._get_all_repos(self.github_client)
            if not repos:
                checkpoint.has_more = False
                return checkpoint

            checkpoint.cached_repo_ids = sorted([repo.id for repo in repos])
            checkpoint.cached_repo = SerializedRepository(
                id=checkpoint.cached_repo_ids[0],
                headers=repos[0].raw_headers,
                raw_data=repos[0].raw_data,
            )
            checkpoint.stage = GithubConnectorStage.PRS
            checkpoint.curr_page = 0
            # save checkpoint with repo ids retrieved
            return checkpoint

        assert checkpoint.cached_repo is not None, "No repo saved in checkpoint"

        # Try to access the requester - different PyGithub versions may use different attribute names
        try:
            # Try direct access to a known attribute name first
            if hasattr(self.github_client, "_requester"):
                requester = self.github_client._requester
            elif hasattr(self.github_client, "_Github__requester"):
                requester = self.github_client._Github__requester
            else:
                # If we can't find the requester attribute, we need to fall back to recreating the repo
                raise AttributeError("Could not find requester attribute")

            repo = checkpoint.cached_repo.to_Repository(requester)
        except Exception as e:
            # If all else fails, re-fetch the repo directly
            logger.warning(
                f"Failed to deserialize repository: {e}. Attempting to re-fetch."
            )
            repo_id = checkpoint.cached_repo.id
            repo = self.github_client.get_repo(repo_id)

        if self.include_prs and checkpoint.stage == GithubConnectorStage.PRS:
            logger.info(f"Fetching PRs for repo: {repo.name}")
            pull_requests = repo.get_pulls(
                state=self.state_filter, sort="updated", direction="desc"
            )

            doc_batch: list[Document] = []
            pr_batch = _get_batch_rate_limited(
                pull_requests, checkpoint.curr_page, self.github_client
            )
            checkpoint.curr_page += 1
            done_with_prs = False
            for pr in pr_batch:
                # we iterate backwards in time, so at this point we stop processing prs
                if (
                    start is not None
                    and pr.updated_at
                    and pr.updated_at.replace(tzinfo=timezone.utc) < start
                ):
                    yield from doc_batch
                    done_with_prs = True
                    break
                # Skip PRs updated after the end date
                if (
                    end is not None
                    and pr.updated_at
                    and pr.updated_at.replace(tzinfo=timezone.utc) > end
                ):
                    continue
                try:
                    doc_batch.append(_convert_pr_to_document(cast(PullRequest, pr)))
                except Exception as e:
                    error_msg = f"Error converting PR to document: {e}"
                    logger.exception(error_msg)
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=str(pr.id), document_link=pr.html_url
                        ),
                        failure_message=error_msg,
                        exception=e,
                    )
                    continue

            # if we found any PRs on the page, yield any associated documents and return the checkpoint
            if not done_with_prs and len(pr_batch) > 0:
                yield from doc_batch
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # prs to get, we move on to issues
            checkpoint.stage = GithubConnectorStage.ISSUES
            checkpoint.curr_page = 0

        checkpoint.stage = GithubConnectorStage.ISSUES

        if self.include_issues and checkpoint.stage == GithubConnectorStage.ISSUES:
            logger.info(f"Fetching issues for repo: {repo.name}")
            issues = repo.get_issues(
                state=self.state_filter, sort="updated", direction="desc"
            )

            doc_batch = []
            issue_batch = _get_batch_rate_limited(
                issues, checkpoint.curr_page, self.github_client
            )
            checkpoint.curr_page += 1
            done_with_issues = False
            for issue in cast(list[Issue], issue_batch):
                # we iterate backwards in time, so at this point we stop processing prs
                if (
                    start is not None
                    and issue.updated_at.replace(tzinfo=timezone.utc) < start
                ):
                    yield from doc_batch
                    done_with_issues = True
                    break
                # Skip PRs updated after the end date
                if (
                    end is not None
                    and issue.updated_at.replace(tzinfo=timezone.utc) > end
                ):
                    continue

                if issue.pull_request is not None:
                    # PRs are handled separately
                    continue

                try:
                    doc_batch.append(_convert_issue_to_document(issue))
                except Exception as e:
                    error_msg = f"Error converting issue to document: {e}"
                    logger.exception(error_msg)
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=str(issue.id),
                            document_link=issue.html_url,
                        ),
                        failure_message=error_msg,
                        exception=e,
                    )
                    continue

            # if we found any issues on the page, yield them and return the checkpoint
            if not done_with_issues and len(issue_batch) > 0:
                yield from doc_batch
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # issues to get, we move on to the FILES stage
            checkpoint.stage = GithubConnectorStage.FILES
            checkpoint.curr_page = 0
        if self.include_files and checkpoint.stage == GithubConnectorStage.FILES:
            logger.info(f"Fetching source files for repo: {repo.name}")
            contents = repo.get_contents("")

            doc_batch = []
            contents_batch = _get_batch_rate_limited(
                contents, checkpoint.curr_page, self.github_client
            )
            checkpoint.curr_page += 1
            done_with_contents = False
            for content in cast(list[ContentFile], contents_batch):
                if (
                    start is not None
                    and content.updated_at.replace(tzinfo=timezone.utc) < start
                ):
                    continue
                    # yield from doc_batch
                    # done_with_contents = True
                    # break
                # Skip files updated after the end date
                if (
                    end is not None
                    and content.updated_at.replace(tzinfo=timezone.utc) > end
                ):
                    continue

                if content.pull_request is not None:
                    # PRs are handled separately
                    continue

                if content.issue is not None:
                    # Issues are handled separately
                    continue

                try:
                    doc_batch.append(self.process_content(content))
                except Exception as e:
                    error_msg = f"Error converting content to document: {e}"
                    logger.exception(error_msg)
                    yield ConnectorFailure(
                        failed_document=DocumentFailure(
                            document_id=str(issue.id),
                            document_link=issue.html_url,
                        ),
                        failure_message=error_msg,
                        exception=e,
                    )
                    continue

            # if we found any issues on the page, yield them and return the checkpoint
            if not done_with_contents and len(contents_batch) > 0:
                yield from doc_batch
                return checkpoint

            # if we went past the start date during the loop or there are no more
            # issues to get, we move on to the next repo
            checkpoint.stage = GithubConnectorStage.PRS
            checkpoint.curr_page = 0

        checkpoint.has_more = len(checkpoint.cached_repo_ids) > 1
        if checkpoint.cached_repo_ids:
            next_id = checkpoint.cached_repo_ids.pop()
            next_repo = self.github_client.get_repo(next_id)
            checkpoint.cached_repo = SerializedRepository(
                id=next_id,
                headers=next_repo.raw_headers,
                raw_data=next_repo.raw_data,
            )

        return checkpoint

    @override
    def load_from_checkpoint(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch,
        checkpoint: GithubConnectorCheckpoint,
    ) -> CheckpointOutput[GithubConnectorCheckpoint]:
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)

        # Move start time back by 3 hours, since some Issues/PRs are getting dropped
        # Could be due to delayed processing on GitHub side
        # The non-updated issues since last poll will be shortcut-ed and not embedded
        adjusted_start_datetime = start_datetime - timedelta(hours=3)

        epoch = datetime.fromtimestamp(0, tz=timezone.utc)
        if adjusted_start_datetime < epoch:
            adjusted_start_datetime = epoch

        return self._fetch_from_github(
            checkpoint, start=adjusted_start_datetime, end=end_datetime
        )

    def validate_connector_settings(self) -> None:
        if self.github_client is None:
            raise ConnectorMissingCredentialError("GitHub credentials not loaded.")

        if not self.repo_owner:
            raise ConnectorValidationError(
                "Invalid connector settings: 'repo_owner' must be provided."
            )

        try:
            if self.repositories:
                if "," in self.repositories:
                    # Multiple repositories specified
                    repo_names = [name.strip() for name in self.repositories.split(",")]
                    if not repo_names:
                        raise ConnectorValidationError(
                            "Invalid connector settings: No valid repository names provided."
                        )

                    # Validate at least one repository exists and is accessible
                    valid_repos = False
                    validation_errors = []

                    for repo_name in repo_names:
                        if not repo_name:
                            continue

                        try:
                            test_repo = self.github_client.get_repo(
                                f"{self.repo_owner}/{repo_name}"
                            )
                            test_repo.get_contents("")
                            valid_repos = True
                            # If at least one repo is valid, we can proceed
                            break
                        except GithubException as e:
                            validation_errors.append(
                                f"Repository '{repo_name}': {e.data.get('message', str(e))}"
                            )

                    if not valid_repos:
                        error_msg = (
                            "None of the specified repositories could be accessed: "
                        )
                        error_msg += ", ".join(validation_errors)
                        raise ConnectorValidationError(error_msg)
                else:
                    # Single repository (backward compatibility)
                    test_repo = self.github_client.get_repo(
                        f"{self.repo_owner}/{self.repositories}"
                    )
                    test_repo.get_contents("")
            else:
                # Try to get organization first
                try:
                    org = self.github_client.get_organization(self.repo_owner)
                    org.get_repos().totalCount  # Just check if we can access repos
                except GithubException:
                    # If not an org, try as a user
                    user = self.github_client.get_user(self.repo_owner)
                    user.get_repos().totalCount  # Just check if we can access repos

        except RateLimitExceededException:
            raise UnexpectedValidationError(
                "Validation failed due to GitHub rate-limits being exceeded. Please try again later."
            )

        except GithubException as e:
            if e.status == 401:
                raise CredentialExpiredError(
                    "GitHub credential appears to be invalid or expired (HTTP 401)."
                )
            elif e.status == 403:
                raise InsufficientPermissionsError(
                    "Your GitHub token does not have sufficient permissions for this repository (HTTP 403)."
                )
            elif e.status == 404:
                if self.repositories:
                    if "," in self.repositories:
                        raise ConnectorValidationError(
                            f"None of the specified GitHub repositories could be found for owner: {self.repo_owner}"
                        )
                    else:
                        raise ConnectorValidationError(
                            f"GitHub repository not found with name: {self.repo_owner}/{self.repositories}"
                        )
                else:
                    raise ConnectorValidationError(
                        f"GitHub user or organization not found: {self.repo_owner}"
                    )
            else:
                raise ConnectorValidationError(
                    f"Unexpected GitHub error (status={e.status}): {e.data}"
                )

        except Exception as exc:
            raise Exception(
                f"Unexpected error during GitHub settings validation: {exc}"
            )

    def validate_checkpoint_json(
        self, checkpoint_json: str
    ) -> GithubConnectorCheckpoint:
        return GithubConnectorCheckpoint.model_validate_json(checkpoint_json)

    def build_dummy_checkpoint(self) -> GithubConnectorCheckpoint:
        return GithubConnectorCheckpoint(
            stage=GithubConnectorStage.PRS, curr_page=0, has_more=True
        )


# if __name__ == "__main__":
#     import time
#     test_connector = GithubSourceConnector(
#         repo_owner="philips-internal",
#         repositories="clinical-platform",
#     )
#     test_connector.load_credentials(
#         {"github_access_token": "os.environ["ACCESS_TOKEN_GITHUB"]"}
#     )

#     document_batches = test_connector.load_from_checkpoint(
#         0, time.time(), test_connector.build_dummy_checkpoint()
#     )

#     current = time.time()
#     one_day_ago = current - 24 * 60 * 60  # 1 day
#     latest_docs = test_connector.poll_source(one_day_ago, current)

if __name__ == "__main__":
    import os

    connector = GithubSourceConnector(
        repo_owner=os.environ["REPO_OWNER"],
        repositories=os.environ["REPOSITORIES"],
    )
    connector.load_credentials(
        {"github_access_token": os.environ["ACCESS_TOKEN_GITHUB"]}
    )
    document_batches = connector.load_from_checkpoint(
        0, time.time(), connector.build_dummy_checkpoint()
    )
    print(next(document_batches))
