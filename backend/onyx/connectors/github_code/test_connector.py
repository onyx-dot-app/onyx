# File: onyx/connectors/github_code/test_connector.py

import unittest
from onyx.connectors.github_code.connector import GitHubCodeConnector, GitHubCodeConnectorConfig

# We will monkeypatch network calls in tests to avoid actual GitHub API calls.
# For simplicity, these tests assume the connector methods are modified to allow injection of fake data or use a local repo.

class DummyGitHubAPIServer:
    """Dummy server to simulate GitHub API responses for testing."""
    def __init__(self):
        # Simulate a repository with two files and two commits
        self.repo_files = {
            "file1.js": "function foo() { return 42; }\n",
            "subdir/file2.rb": "def bar\n  puts 'hello'\nend\n"
        }
        self.last_commit = "commit123"
        self.new_commit = "commit124"
        self.changed_file = "file1.js"
    def get_repo_zip(self):
        # Return a zip bytes containing repo_files
        import io, zipfile
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w') as zf:
            for path, content in self.repo_files.items():
                zf.writestr(path, content)
        return zip_buffer.getvalue()
    def get_commits_since(self, sha):
        # If sha == last_commit, return a list with one new commit
        if sha == self.last_commit:
            return [ {"sha": self.new_commit} ]
        else:
            return []
    def get_commit_details(self, sha):
        # For new_commit, simulate that file1.js changed
        if sha == self.new_commit:
            return { "files": [ {"filename": self.changed_file} ] }
        return { "files": [] }
    def get_file_content(self, path):
        return self.repo_files.get(path, "")

class GitHubCodeConnectorTest(unittest.TestCase):
    def setUp(self):
        # Setup dummy API server and monkeypatch requests
        self.api = DummyGitHubAPIServer()
        # Monkeypatch requests in the connector module
        import types
        import onyx.connectors.github_code.connector as connector_module
        connector_module.requests = types.SimpleNamespace()  # dummy object to hold our fakes
        connector_module.requests.get = self._dummy_requests_get

        # Prepare config for the connector
        config = GitHubCodeConnectorConfig(
            repo_owner="dummy", repo_name="dummyrepo", branch="main", access_token=None,
            include_file_patterns=["*.js","*.rb"], exclude_dir_patterns=[]
        )
        # Instantiate connector
        self.connector = GitHubCodeConnector(config)

    def _dummy_requests_get(self, url, headers=None, timeout=10):
        """Fake requests.get behavior depending on URL."""
        if "zipball" in url:
            # Return dummy zip content
            class DummyResp:
                status_code = 200
                def __init__(self, content): 
                    self.content = content
                def raise_for_status(self): 
                    return None
            return DummyResp(self.api.get_repo_zip())
        elif "commits?" in url:
            # Commits since endpoint
            class DummyResp:
                status_code = 200
                def __init__(self, data): 
                    self._data = data
                def json(self): 
                    return data
                def raise_for_status(self): 
                    return None
            # parse 'since' from URL
            return DummyResp(self.api.get_commits_since(sha=self.api.last_commit))
        elif "commits/" in url:
            # Commit details endpoint
            commit_sha = url.split("/")[-1]
            class DummyResp:
                status_code = 200
                def json(self_inner): 
                    return self.api.get_commit_details(commit_sha)
                def raise_for_status(self): 
                    return None
            return DummyResp()
        elif "raw.githubusercontent.com" in url:
            # Raw file content
            path = "/".join(url.split("/", 5)[5:])  # extract path after .../branch/
            class DummyResp:
                status_code = 200
                text = ""
                def __init__(self, text): 
                    self.text = text
            return DummyResp(self.api.get_file_content(path))
        else:
            # default dummy
            class DummyResp:
                status_code = 404
                def raise_for_status(self): 
                    raise Exception("Not Found")
            return DummyResp()

    def test_full_load_indexes_all_files(self):
        docs = self.connector.load_from_source()
        # Should index both files in dummy repo
        indexed_paths = {doc.metadata["path"] for doc in docs}
        self.assertIn("file1.js", indexed_paths)
        self.assertIn("subdir/file2.rb", indexed_paths)
        # Each chunk's embedding vector should be non-empty
        for doc in docs:
            vec = doc.embedding
            self.assertIsInstance(vec, list)
            self.assertTrue(len(vec) > 0)

    def test_poll_fetches_new_changes(self):
        # First, simulate initial load (set a checkpoint)
        _ = self.connector.load_from_source()
        last_commit = self.api.last_commit
        # Simulate a poll with a new commit
        new_docs, new_checkpoint = self.connector.poll_source(last_checkpoint=last_commit)
        # We expect file1.js was changed, so it should appear in new_docs
        paths = [doc.metadata["path"] for doc in new_docs]
        self.assertIn("file1.js", paths)
        # New checkpoint should be updated to new_commit
        self.assertEqual(new_checkpoint, self.api.new_commit)
        # No duplicate indexing of unchanged files (file2.rb should not be in new_docs)
        self.assertNotIn("subdir/file2.rb", paths)

    def test_chunking_small_file_no_split(self):
        code = "print('x')"  # very short code
        chunks, vectors = self.connector.embed_pipeline.chunk_and_embed(code, language=None)
        # Should not split into multiple chunks
        self.assertEqual(len(chunks), 1)
        self.assertEqual(len(vectors), 1)

    def test_ast_chunking_produces_function_chunks(self):
        js_code = "function f1(){console.log('a')}\nfunction f2(){console.log('b')}\n"
        chunks, _ = self.connector.embed_pipeline.chunk_and_embed(js_code, language="javascript")
        # Expect two chunks (one per function)
        self.assertEqual(len(chunks), 2)
        self.assertTrue(chunks[0].strip().startswith("function f1"))
        self.assertTrue(chunks[1].strip().startswith("function f2"))

# Run tests (if this file is executed directly)
if __name__ == "__main__":
    unittest.main()
