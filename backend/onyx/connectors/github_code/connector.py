# File: onyx/connectors/github_code/connector.py

import io
import hashlib
import requests
from typing import Any, Optional, Tuple, List
from datetime import datetime

from onyx.connectors.interfaces import LoadConnector, PollConnector, CheckpointedConnector
from onyx.connectors.github_code.config import GitHubCodeConnectorConfig
from onyx.connectors.github_code.embedding import CodeEmbeddingPipeline
from onyx.connectors.models import Document


class GitHubCodeConnector(LoadConnector, PollConnector, CheckpointedConnector):
    """Onyx Connector to index GitHub repository code content using RAG techniques."""
    def __init__(self, config: GitHubCodeConnectorConfig):
        self.config = config
        # Prepare embedding pipeline with chosen model
        self.embed_pipeline = CodeEmbeddingPipeline(
            model_name=config.model_name,
            openai_model=config.openai_model,
            cohere_model=config.cohere_model,
            chunk_size=config.chunk_size,
            chunk_overlap=config.chunk_overlap,
        )
        # Cache for content hashes to avoid reprocessing unchanged files in one run
        self._content_hash_cache: dict[str, str] = {}

    def load_from_source(self) -> List[Document]:
        """Initial full indexing of the repository (fetch all files and index them)."""
        repo_owner = self.config.repo_owner
        repo_name = self.config.repo_name
        branch = self.config.branch
        # Use GitHub archive API to download a zip of the repo at specified branch
        zip_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/zipball/{branch}"
        headers = {}
        if self.config.access_token:
            headers["Authorization"] = f"token {self.config.access_token.get_secret_value()}"
        resp = requests.get(zip_url, headers=headers, timeout=60)
        resp.raise_for_status()
        zip_content = resp.content

        docs: List[Document] = []
        with io.BytesIO(zip_content) as zbuf:
            with requests.compat.zipfile.ZipFile(zbuf) as zf:
                for file_info in zf.infolist():
                    file_path = file_info.filename
                    # Skip directories and filter by include/exclude patterns
                    if file_info.is_dir():
                        continue
                    if not self._include_file(file_path):
                        continue
                    try:
                        file_bytes = zf.read(file_info)
                        text = file_bytes.decode("utf-8", errors="ignore")
                    except Exception as e:
                        # Log and skip files that cannot be read/decoded
                        print(f"[WARN] Skipping {file_path}: {e}")
                        continue
                    docs.extend(self._process_file(file_path, text))
        return docs

    def poll_source(self, last_checkpoint: Optional[Any]) -> Tuple[List[Document], Any]:
        """
        Poll for new commits since last checkpoint (last commit SHA).
        Returns a tuple of (new_documents, new_checkpoint).
        """
        repo_owner = self.config.repo_owner
        repo_name = self.config.repo_name
        branch = self.config.branch
        headers = {}
        if self.config.access_token:
            headers["Authorization"] = f"token {self.config.access_token.get_secret_value()}"

        # If no checkpoint, do a full load
        if not last_checkpoint:
            docs = self.load_from_source()
            latest_commit = self._get_latest_commit_sha(headers)
            return docs, latest_commit

        # Get list of commits since last_checkpoint
        commits_url = (
            f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits"
            f"?sha={branch}&since={last_checkpoint}"
        )
        resp = requests.get(commits_url, headers=headers, timeout=30)
        resp.raise_for_status()
        commits = resp.json()
        if not commits:
            # No new commits
            return [], last_checkpoint

        # Determine all changed files in these commits
        changed_files: set[str] = set()
        for commit in commits:
            commit_sha = commit["sha"]
            commit_url = f"https://api.github.com/repos/{repo_owner}/{repo_name}/commits/{commit_sha}"
            c_resp = requests.get(commit_url, headers=headers, timeout=15)
            if c_resp.status_code != 200:
                continue
            commit_data = c_resp.json()
            files = commit_data.get("files", [])
            for f in files:
                filename = f.get("filename")
                if filename:
                    changed_files.add(filename)
        if not changed_files:
            return [], commits[0]["sha"]

        new_docs: List[Document] = []
        for filepath in changed_files:
            if not self._include_file(filepath):
                continue
            file_url = f"https://raw.githubusercontent.com/{repo_owner}/{repo_name}/{branch}/{filepath}"
            try:
                f_resp = requests.get(file_url, headers=headers, timeout=15)
                if f_resp.status_code != 200:
                    continue
                text = f_resp.text
            except Exception as e:
                print(f"[ERROR] Failed to fetch {filepath}: {e}")
                continue
            new_docs.extend(self._process_file(filepath, text))

        latest_commit = commits[0]["sha"]
        return new_docs, latest_commit

    def _include_file(self, file_path: str) -> bool:
        """Check if file_path matches include patterns and is not excluded."""
        from fnmatch import fnmatch

        for pattern in self.config.exclude_dir_patterns:
            if fnmatch(file_path, pattern):
                return False
        for pattern in self.config.include_file_patterns:
            if fnmatch(file_path, pattern):
                return True
        return False

    def _process_file(self, file_path: str, text: str) -> List[Document]:
        """Split a file’s content into chunks, embed them, and wrap in Document objects."""
        docs: List[Document] = []
        if not text:
            return docs

        content_hash = hashlib.md5(text.encode("utf-8", errors="ignore")).hexdigest()
        prev_hash = self._content_hash_cache.get(file_path)
        if prev_hash == content_hash:
            return docs  # skip re-processing if already done this run
        self._content_hash_cache[file_path] = content_hash

        language = self._infer_language(file_path)
        chunks, vectors = self.embed_pipeline.chunk_and_embed(text, language)
        for chunk_text, vec in zip(chunks, vectors):
            metadata = {
                "repo": f"{self.config.repo_owner}/{self.config.repo_name}",
                "path": file_path,
                "timestamp": datetime.utcnow().isoformat() + "Z",
                "model": self.config.model_name,
            }
            doc = Document(text=chunk_text, embedding=vec, metadata=metadata)
            docs.append(doc)
        return docs

    def _infer_language(self, file_path: str) -> Optional[str]:
        """Infer programming language from file extension."""
        fn = file_path.lower()
        if fn.endswith((".js", ".jsx", ".ts", ".tsx")):
            return "javascript"
        if fn.endswith(".rb"):
            return "ruby"
        if fn.endswith((".cs", ".fs", ".sln", ".csproj")):
            return "csharp"
        if fn.endswith(".py"):
            return "python"
        return None

    def _get_latest_commit_sha(self, headers: dict) -> Optional[str]:
        """Get the latest commit SHA for the repo’s configured branch."""
        api_url = f"https://api.github.com/repos/{self.config.repo_owner}/{self.config.repo_name}/commits/{self.config.branch}"
        try:
            resp = requests.get(api_url, headers=headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return data.get("sha")
        except Exception as e:
            print(f"[WARN] Could not fetch latest commit: {e}")
            return None


# # If your code uses a registry-style import, you might also register here:
# TRY_REGISTER = True
# if TRY_REGISTER:
#     from onyx.connectors.registry import register_connector

#     register_connector(
#         connector_name="github_code",
#         connector_class=GitHubCodeConnector,
#         config_class=GitHubCodeConnectorConfig,
#         friendly_name="GitHub Code Connector",
#         connects_to="GitHub Repository (Code)",
#         description="Indexes repository source code (files) with semantic code embeddings",
#     )
