	# File: backend/onyx/connectors/github_code/connector.py

import os
from datetime import datetime, timezone
from typing import Any, List, Optional, Generator
from fnmatch import fnmatch

import requests

from onyx.connectors.interfaces import (
    LoadConnector,
    PollConnector,
    GenerateDocumentsOutput,
    SecondsSinceUnixEpoch,
)
from onyx.connectors.models import (
    Document,
    TextSection,
    ConnectorMissingCredentialError,
)
from onyx.configs.constants import DocumentSource
from onyx.utils.logger import setup_logger

logger = setup_logger()


class GitHubCodeConnector(LoadConnector, PollConnector):
    """Onyx Connector to index GitHub repository code content."""
    
    def __init__(
        self,
        repo_owner: str,
        repositories: str = None,
        include_file_patterns: list[str] = None,
        exclude_dir_patterns: list[str] = None,
        batch_size: int = 10,
        **kwargs
    ):
        """
        Initialize the GitHub Code Connector.
        
        Args:
            repo_owner: GitHub username or organization
            repositories: Comma-separated list of repository names, or None for all repos
            include_file_patterns: File patterns to include
            exclude_dir_patterns: Directory patterns to exclude
            batch_size: Number of documents to yield at once
        """
        self.repo_owner = repo_owner
        self.repositories = repositories
        self.branch = kwargs.get('branch', 'main')
        self.batch_size = batch_size
        
        # Default file patterns for code files
        self.include_file_patterns = include_file_patterns or [
            "*.py", "*.js", "*.ts", "*.jsx", "*.tsx", "*.java", "*.cpp", "*.c", "*.h",
            "*.rb", "*.cs", "*.go", "*.rs", "*.php", "*.swift", "*.kt",
            "*.scala", "*.sh", "*.yml", "*.yaml", "*.json", "*.xml", "*.md"
        ]
        
        self.exclude_dir_patterns = exclude_dir_patterns or [
            "**/node_modules/**", "**/vendor/**", "**/dist/**", "**/build/**", 
            "**/__pycache__/**", "**/.git/**", "**/target/**", "**/bin/**", 
            "**/obj/**", "**/.idea/**", "**/.vscode/**", "**/*.min.js"
        ]
        
        # GitHub client info
        self.access_token: Optional[str] = None
        self.github_headers: dict[str, str] = {}

    def load_credentials(self, credentials: dict[str, Any]) -> dict[str, Any] | None:
        """Load credentials such as a GitHub access token."""
        # Try multiple possible credential keys
        token = (credentials.get("github_access_token") or 
                credentials.get("github_token") or 
                credentials.get("access_token") or
                credentials.get("github_code_access_token"))
                
        if not token:
            raise ConnectorMissingCredentialError("GitHub")
            
        self.access_token = token
        self.github_headers = {
            "Authorization": f"token {token}",
            "Accept": "application/vnd.github.v3+json"
        }
        
        logger.info(f"Loaded GitHub credentials for {self.repo_owner}")
        return None

    def load_from_state(self) -> GenerateDocumentsOutput:
        """Yield all documents in the repository."""
        logger.info(f"Starting full indexing for GitHub user/org: {self.repo_owner}")
        
        try:
            repos = self._get_repositories()
            logger.info(f"Found {len(repos)} repositories to index")
            
            document_batch = []
            
            for repo in repos:
                repo_name = repo['name']
                logger.info(f"Indexing repository: {self.repo_owner}/{repo_name}")
                
                try:
                    repo_docs = self._load_repository(repo)
                    logger.info(f"Found {len(repo_docs)} documents in {repo_name}")
                    
                    for doc in repo_docs:
                        document_batch.append(doc)
                        
                        if len(document_batch) >= self.batch_size:
                            yield document_batch
                            document_batch = []
                            
                except Exception as e:
                    logger.error(f"Error indexing repository {repo_name}: {e}")
                    continue
            
            # Yield remaining documents
            if document_batch:
                yield document_batch
                
        except Exception as e:
            logger.error(f"Error during GitHub indexing: {e}")
            raise

    def poll_source(
        self,
        start: SecondsSinceUnixEpoch,
        end: SecondsSinceUnixEpoch
    ) -> GenerateDocumentsOutput:
        """Poll for changes in the specified time range."""
        start_datetime = datetime.fromtimestamp(start, tz=timezone.utc)
        end_datetime = datetime.fromtimestamp(end, tz=timezone.utc)
        
        logger.info(f"Polling GitHub for changes between {start_datetime} and {end_datetime}")
        
        try:
            repos = self._get_repositories()
            document_batch = []
            
            for repo in repos:
                repo_name = repo['name']
                
                # Get commits in the time range
                commits_url = (
                    f"https://api.github.com/repos/{self.repo_owner}/{repo_name}/commits"
                    f"?since={start_datetime.isoformat()}&until={end_datetime.isoformat()}"
                )
                
                try:
                    resp = requests.get(commits_url, headers=self.github_headers, timeout=30)
                    if resp.status_code != 200:
                        continue
                        
                    commits = resp.json()
                    if not commits:
                        continue
                        
                    logger.info(f"Found {len(commits)} commits in {repo_name}")
                    
                    # Get changed files
                    changed_files = self._get_changed_files(repo_name, commits)
                    
                    # Process changed files
                    for filepath in changed_files:
                        docs = self._process_changed_file(repo, filepath)
                        for doc in docs:
                            document_batch.append(doc)
                            
                            if len(document_batch) >= self.batch_size:
                                yield document_batch
                                document_batch = []
                                
                except Exception as e:
                    logger.error(f"Error polling repository {repo_name}: {e}")
                    continue
            
            # Yield remaining documents
            if document_batch:
                yield document_batch
                
        except Exception as e:
            logger.error(f"Error during GitHub polling: {e}")
            raise

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
                # Try user first
                api_url = f"https://api.github.com/users/{self.repo_owner}/repos?page={page}&per_page=100"
                resp = requests.get(api_url, headers=self.github_headers, timeout=30)
                
                if resp.status_code == 404:
                    # Try as organization
                    api_url = f"https://api.github.com/orgs/{self.repo_owner}/repos?page={page}&per_page=100"
                    resp = requests.get(api_url, headers=self.github_headers, timeout=30)
                
                if resp.status_code == 200:
                    page_repos = resp.json()
                    if not page_repos:
                        break
                    repos.extend(page_repos)
                    page += 1
                    
                    # GitHub API has a limit, don't fetch too many
                    if len(repos) >= 100:
                        logger.warning(f"Limiting to first 100 repositories for {self.repo_owner}")
                        break
                else:
                    logger.error(f"Could not fetch repositories: {resp.status_code}")
                    break
                    
        return repos

    def _load_repository(self, repo_info: dict) -> List[Document]:
        """Load all files from a single repository."""
        repo_name = repo_info['name']
        default_branch = repo_info.get('default_branch', 'main')
        branch = self.branch if self.branch != 'main' else default_branch
        
        docs = []
        
        # Use the tree API to get all files
        tree_url = f"https://api.github.com/repos/{self.repo_owner}/{repo_name}/git/trees/{branch}?recursive=1"
        
        try:
            resp = requests.get(tree_url, headers=self.github_headers, timeout=60)
            if resp.status_code != 200:
                logger.error(f"Could not fetch tree for {repo_name}: {resp.status_code}")
                return docs
                
            tree_data = resp.json()
            files = [item for item in tree_data.get('tree', []) if item['type'] == 'blob']
            
            logger.info(f"Found {len(files)} files in {repo_name}")
            
            # Process files in batches
            for file_info in files:
                file_path = file_info['path']
                
                if not self._include_file(file_path):
                    continue
                    
                # Get file content
                file_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{repo_name}/{branch}/{file_path}"
                
                try:
                    file_resp = requests.get(file_url, headers=self.github_headers, timeout=30) 
                    if file_resp.status_code == 200:
                        content = file_resp.text
                        
                        # Skip empty or very large files
                        if not content or len(content) > 1024 * 1024:  # 1MB limit
                            continue
                            
                        doc = self._create_document(repo_name, file_path, content, branch)
                        if doc:
                            docs.append(doc)
                            
                except Exception as e:
                    logger.error(f"Error fetching file {file_path}: {e}")
                    continue
                    
        except Exception as e:
            logger.error(f"Error loading repository {repo_name}: {e}")
            
        return docs

    def _get_changed_files(self, repo_name: str, commits: List[dict]) -> set:
        """Get all changed files from a list of commits."""
        changed_files = set()
        
        for commit in commits:
            commit_sha = commit['sha']
            commit_url = f"https://api.github.com/repos/{self.repo_owner}/{repo_name}/commits/{commit_sha}"
            
            try:
                resp = requests.get(commit_url, headers=self.github_headers, timeout=30)
                if resp.status_code == 200:
                    commit_data = resp.json()
                    
                    for file_info in commit_data.get('files', []):
                        filename = file_info.get('filename')
                        if filename and self._include_file(filename):
                            changed_files.add(filename)
            except Exception as e:
                logger.error(f"Error fetching commit {commit_sha}: {e}")
                
        return changed_files

    def _process_changed_file(self, repo_info: dict, filepath: str) -> List[Document]:
        """Process a single changed file."""
        repo_name = repo_info['name']
        default_branch = repo_info.get('default_branch', 'main')
        branch = self.branch if self.branch != 'main' else default_branch
        
        file_url = f"https://raw.githubusercontent.com/{self.repo_owner}/{repo_name}/{branch}/{filepath}"
        
        try:
            resp = requests.get(file_url, headers=self.github_headers, timeout=30)
            if resp.status_code == 200:
                content = resp.text
                if not content or len(content) > 1024 * 1024:
                    return []
                
                doc = self._create_document(repo_name, filepath, content, branch)
                return [doc] if doc else []
        except Exception as e:
            logger.error(f"Error fetching file {filepath}: {e}")
            
        return []

    def _include_file(self, file_path: str) -> bool:
        """Check if file_path matches include patterns and is not excluded."""
        # Normalize path separators
        file_path = file_path.replace('\\', '/')
        
        # Check exclusions first
        for pattern in self.exclude_dir_patterns:
            if fnmatch(file_path, pattern):
                return False
                
        # Check inclusions
        for pattern in self.include_file_patterns:
            if fnmatch(file_path, pattern):
                return True
                
        return False

    def _create_document(self, repo_name: str, file_path: str, content: str, branch: str) -> Optional[Document]:
        """Create a Document object from file content."""
        if not content or not content.strip():
            return None
            
        # Create a unique document ID
        doc_id = f"github://{self.repo_owner}/{repo_name}/{file_path}"
        
        # Create the document URL
        doc_url = f"https://github.com/{self.repo_owner}/{repo_name}/blob/{branch}/{file_path}"
        
        # Extract just the filename for the title
        filename = os.path.basename(file_path)
        
        try:
            # Create Section with proper structure - pass link and text as keyword arguments
            section = TextSection(link=doc_url, text=content)
            
            # Create the document
            doc = Document(
                id=doc_id,
                sections=[section],  # Pass the Section object, not a dict
                source=DocumentSource.GITHUB_CODE,
                semantic_identifier=f"{repo_name}/{file_path}",
                doc_updated_at=datetime.now(timezone.utc),
                primary_owners=[],
                secondary_owners=[],
                metadata={
                    "repo_owner": self.repo_owner,
                    "repo_name": repo_name,
                    "file_path": file_path,
                    "filename": filename,
                    "language": self._infer_language(file_path) or "unknown",
                }
            )
            
            return doc
            
        except Exception as e:
            logger.error(f"Error creating document for {file_path}: {e}")
            return None

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
            '.c': 'c',
            '.h': 'c',
            '.cs': 'csharp',
            '.rb': 'ruby',
            '.go': 'go',
            '.rs': 'rust',
            '.php': 'php',
            '.swift': 'swift',
            '.kt': 'kotlin',
            '.scala': 'scala',
            '.sh': 'bash',
            '.yml': 'yaml',
            '.yaml': 'yaml',
            '.json': 'json',
            '.xml': 'xml',
            '.md': 'markdown'
        }
        
        file_lower = file_path.lower()
        for ext, lang in ext_to_lang.items():
            if file_lower.endswith(ext):
                return lang
                
        return None