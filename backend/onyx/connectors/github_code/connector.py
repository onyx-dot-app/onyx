# File: onyx/connectors/github_code/connector.py

import io
import os
import hashlib
from datetime import datetime, timezone
from typing import Any, List, Optional, Tuple, Generator
from fnmatch import fnmatch

import requests
from pydantic import SecretStr

from onyx.connectors.interfaces import (
    LoadConnector,
    PollConnector,
    GenerateDocumentsOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.github_code.embedding import CodeEmbeddingPipeline
from onyx.connectors.models import Document, Section, ConnectorMissingCredentialError
from onyx.configs.constants import DocumentSource
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GitHubCodeConnector(LoadConnector, PollConnector):
    """Onyx Connector to index GitHub repository code content using RAG techniques."""
    
    def __init__(
        self,
        repo_owner: str,
        repositories: str = None,  # Accept 'repositories' parameter from the UI
        include_file_patterns: list[str] = None,
        exclude_dir_patterns: list[str] = None,
        model_name: str = "codebert",
        openai_model: str = "text-embedding-ada-002",
        cohere_model: str = "embed-english-v2.0",
        chunk_size: int = 256,
        chunk_overlap: int = 50,
        **kwargs  # Accept any additional parameters
    ):
        """
        Initialize the GitHub Code Connector.
        
        Args:
            repo_owner: GitHub username or organization
            repositories: Comma-separated list of repository names, or None for all repos
            include_file_patterns: File patterns to include (default: common code files)
            exclude_dir_patterns: Directory patterns to exclude (default: node_modules, etc.)
            model_name: Embedding model to use
            openai_model: OpenAI model name if using OpenAI
            cohere_model: Cohere model name if using Cohere
            chunk_size: Maximum tokens per chunk
            chunk_overlap: Token overlap between chunks
        """
        self.repo_owner = repo_owner
        self.repositories = repositories  # Can be None (all repos) or comma-separated string
        self.branch = kwargs.get('branch', 'main')
        
        # Default file patterns for code files
        self.include_file_patterns = include_file_patterns or [
            "*.py", "*.js", "*.ts", "*.jsx", "*.tsx", "*.java", "*.cpp", "*.c", "*.h",
            "*.rb", "*.cs", "*.fs", "*.go", "*.rs", "*.php", "*.swift", "*.kt",
            "*.scala", "*.r", "*.m", "*.mm", "*.sh", "*.bash", "*.zsh",
            "*.yml", "*.yaml", "*.json", "*.xml", "*.md", "*.rst"
        ]
        
        self.exclude_dir_patterns = exclude_dir_patterns or [
            "node_modules/*", "vendor/*", "dist/*", "build/*", "*.min.js",
            "__pycache__/*", "*.pyc", ".git/*", ".svn/*", "target/*",
            "bin/*", "obj/*", ".idea/*", ".vscode/*", "*.egg-info/*"
        ]
        
        # Prepare embedding pipeline with chosen model
        self.embed_pipeline = CodeEmbeddingPipeline(
            model_name=model_name,
            openai_model=openai_model,
            cohere_model=cohere_model,
            chunk_size=chunk_size,
            chunk_overlap=chunk_overlap,
        )
        
        # Cache for content hashes to avoid reprocessing unchanged files
        self._content_hash_cache: dict[str, str] = {}
        
        # GitHub client info
        self.access_token: Optional[str] = None
        self.github_headers: dict[str, str] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load credentials such as a GitHub access token."""
        token = credentials.get("github_access_token") or credentials.get("access_token")
        if not token:
            raise ConnectorMissingCredentialError("GitHub")
            
        self.access_token = token
        self.github_headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Yield all documents in the repository as a single batch."""
        docs = self._load_all_repositories()
        yield docs

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll for changes in the specified time range."""
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        
        docs = self._poll_repositories(start_datetime, end_datetime)
        yield docs

    def _get_repositories(self) -> List[dict]:
        """Get list of repositories to index based on configuration."""
        if not self.access_token:
            raise ConnectorMissingCredentialError("GitHub")
            
        repos = []
        
        if self.repositories:
            # Specific repositories specified
            repo_names = [name.strip() for name in self.repositories.split(',')]
            for repo_name in repo_names:
                if not repo_name:
                    continue
                    
                api_url = f"https://api.github.com/repos/{self.repo_owner}/{repo_name}"
                try:
                    resp = requests.get(api_url, headers=self.github_headers, timeout=30)
                    if resp.status_code == 200:
                        repos.append(resp.json())
                    else:
                        logger.warning(f"Could not access repository {self.repo_owner}/{repo_name}: {resp.status_code}")
                except Exception as e:
                    logger.error(f"Error fetching repository {repo_name}: {e}")
        else:
            # Get all repositories for the user/org
            page = 1
            while True:
                api_url = f"https://api.github.com/users/{self.repo_owner}/repos?page={page}&per_page=100"
                try:
                    resp = requests.get(api_url, headers=self.github_headers, timeout=30)
                    if resp.status_code != 200:
                        # Try as organization
                        api_url = f"https://api.github.com/orgs/{self.repo_owner}/repos?page={page}&per_page=100"
                        resp = requests.get(api_url, headers=self.github_headers, timeout=30)
                    
                    if resp.status_code == 200:
                        page_repos = resp.json()
                        if not page_repos:
                            break
                        repos.extend(page_repos)
                        page += 1
                    else:
                        logger.error(f"Could not fetch repositories: {resp.status_code}")
                        break
                except Exception as e:
                    logger.error(f"Error fetching repositories: {e}")
                    break
                    
        return repos

    def _load_all_repositories(self) -> List[Document]:
        """Load all configured repositories."""
        docs = []
        repos = self._get_repositories()
        
        for repo in repos:
            repo_name = repo['name']
            logger.info(f"Indexing repository: {self.repo_owner}/{repo_name}")
            
            try:
                repo_docs = self._load_repository(repo)
                docs.extend(repo_docs)
            except Exception as e:
                logger.error(f"Error indexing repository {repo_name}: {e}")
                continue
                
        return docs

    def _load_repository(self, repo_info: dict) -> List[Document]:
        """Load all files from a single repository."""
        repo_name = repo_info['name']
        default_branch = repo_info.get('default_branch', 'main')
        branch = self.branch if self.branch != 'main' else default_branch
        
        # Use GitHub archive API to download a zip of the repo
        zip_url = f"https://api.github.com/repos/{self.repo_owner}/{repo_name}/zipball/{branch}"
        
        try:
            resp = requests.get(zip_url, headers=self.github_headers, timeout=60, stream=True)
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if resp.status_code == 404:
                # Try with main branch if specified branch doesn't exist
                zip_url = f"https://api.github.com/repos/{self.repo_owner}/{repo_name}/zipball/main"
                resp = requests.get(zip_url, headers=self.github_headers, timeout=60, stream=True)
                resp.raise_for_status()
            else:
                raise
                
        zip_content = resp.content

        docs: List[Document] = []
        with io.BytesIO(zip_content) as zbuf:
            import zipfile
            with zipfile.ZipFile(zbuf) as zf:
                for file_info in zf.infolist():
                    file_path = file_info.filename
                    
                    # Skip directories
                    if file_info.is_dir():
                        continue
                        
                    # Skip files based on include/exclude patterns
                    if not self._include_file(file_path):
                        continue
                        
                    try:
                        file_bytes = zf.read(file_info)
                        text = file_bytes.decode("utf-8", errors="ignore")
                    except Exception as e:
                        logger.debug(f"Skipping {file_path}: {e}")
                        continue
                        
                    # Process the file and create documents
                    file_docs = self._process_file(repo_name, file_path, text)
                    docs.extend(file_docs)
                    
        return docs

    def _poll_repositories(self, start: datetime, end: datetime) -> List[Document]:
        """Poll repositories for changes in the given time range."""
        docs = []
        repos = self._get_repositories()
        
        for repo in repos:
            repo_name = repo['name']
            
            # Get commits in the time range
            commits_url = (
                f"https://api.github.com/repos/{self.repo_owner}/{repo_name}/commits"
                f"?since={start.isoformat()}&until={end.isoformat()}"
            )
            
            try:
                resp = requests.get(commits_url, headers=self.github_headers, timeout=30)
                resp.raise_for_status()
                commits = resp.json()
            except Exception as e:
                logger.error(f"Error fetching commits for {repo_name}: {e}")
                continue
                
            if not commits:
                continue
                
            logger.info(f"Found {len(commits)} commits in {repo_name} since {start}")
            
            # Get all changed files
            changed_files = set()
            for commit in commits:
                commit_sha = commit['sha']
                commit_url = f"https://api.github.com/repos/{self.repo_owner}/{repo_name}/commits/{commit_sha}"
                
                try:
                    c_resp = requests.get(commit_url, headers=self.github_headers, timeout=30)
                    c_resp.raise_for_status()
                    commit_data = c_resp.json()
                    
                    for file_info in commit_data.get('files', []):
                        filename = file_info.get('filename')
                        if filename and self._include_file(filename):
                            changed_files.add(filename)
                except Exception as e:
                    logger.error(f"Error fetching commit {commit_sha}: {e}")
                    continue
                    
            # Process changed files
            default_branch = repo.get('default_branch', 'main')
            branch = self.branch if self.branch != 'main' else default_branch
            
            for filepath in changed_files:
                file_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{repo_name}/{branch}/{filepath}"
                
                try:
                    f_resp = requests.get(file_url, headers=self.github_headers, timeout=15)
                    if f_resp.status_code == 200:
                        text = f_resp.text
                        file_docs = self._process_file(repo_name, filepath, text)
                        docs.extend(file_docs)
                except Exception as e:
                    logger.error(f"Error fetching file {filepath}: {e}")
                    continue
                    
        return docs

    def _include_file(self, file_path: str) -> bool:
        """Check if file_path matches include patterns and is not excluded."""
        # Check exclusions first
        for pattern in self.exclude_dir_patterns:
            if fnmatch(file_path, pattern):
                return False
                
        # Check inclusions
        for pattern in self.include_file_patterns:
            if fnmatch(file_path, pattern):
                return True
                
        return False

    def _process_file(self, repo_name: str, file_path: str, text: str) -> List[Document]:
        """Split a file's content into chunks and create Document objects."""
        docs: List[Document] = []
        if not text or not text.strip():
            return docs

        # Skip files that are too large (> 1MB)
        if len(text) > 1024 * 1024:
            logger.warning(f"Skipping large file {file_path} ({len(text)} bytes)")
            return docs

        # Create a hash to check if content changed
        content_hash = hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()
        cache_key = f"{repo_name}/{file_path}"
        
        if self._content_hash_cache.get(cache_key) == content_hash:
            return docs  # Skip if content hasn't changed
            
        self._content_hash_cache[cache_key] = content_hash

        # Infer language from file extension
        language = self._infer_language(file_path)
        
        # Get chunks and embeddings
        try:
            chunks, vectors = self.embed_pipeline.chunk_and_embed(text, language)
        except Exception as e:
            logger.error(f"Error processing {file_path}: {e}")
            return docs

        # Create documents for each chunk
        for i, (chunk_text, embedding) in enumerate(zip(chunks, vectors)):
            # Create a unique ID for this chunk
            doc_id = f"github://{self.repo_owner}/{repo_name}/{file_path}#chunk{i}"
            
            # Create the document
            doc = Document(
                id=doc_id,
                sections=[Section(
                    link=f"https://github.com/{self.repo_owner}/{repo_name}/blob/{self.branch}/{file_path}",
                    text=chunk_text
                )],
                source=DocumentSource.GITHUB,
                semantic_identifier=f"{repo_name}/{file_path}",
                doc_updated_at=datetime.now(timezone.utc),
                primary_owners=[],
                secondary_owners=[],
                metadata={
                    "repo_owner": self.repo_owner,
                    "repo_name": repo_name,
                    "file_path": file_path,
                    "language": language or "unknown",
                    "chunk_index": i,
                    "total_chunks": len(chunks),
                    "embedding_model": self.embed_pipeline.model_name
                }
            )
            
            # Add embedding if available
            if embedding:
                doc.embeddings = embedding
                
            docs.append(doc)
            
        logger.debug(f"Created {len(docs)} documents for {file_path}")
        return docs

    def _infer_language(self, file_path: str) -> Optional[str]:
        """Infer programming language from file extension."""
        ext_to_lang = {
            '.py': 'python',
            '.js': 'javascript',
            '.jsx': 'javascript',
            '.ts': 'typescript',
            '.tsx': 'typescript',
            '.java': 'java',
            '.cpp': 'cpp',
            '.cc': 'cpp',
            '.cxx': 'cpp',
            '.c': 'c',
            '.h': 'c',
            '.hpp': 'cpp',
            '.cs': 'csharp',
            '.fs': 'fsharp',
            '.rb': 'ruby',
            '.go': 'go',
            '.rs': 'rust',
            '.php': 'php',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.r': 'r',
            '.m': 'objc',
            '.mm': 'objcpp',
            '.sh': 'bash',
            '.bash': 'bash',
            '.zsh': 'zsh',
            '.yml': 'yaml',
            '.yaml': 'yaml',
            '.json': 'json',
            '.xml': 'xml',
            '.md': 'markdown',
            '.rst': 'rst'
        }
        
        file_lower = file_path.lower()
        for ext, lang in ext_to_lang.items():
            if file_lower.endswith(ext):
                return lang
                
        return None