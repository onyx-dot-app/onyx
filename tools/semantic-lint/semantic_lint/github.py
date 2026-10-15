"""GitHub REST reads and the check run write, plus the JSON transport Jev shares."""

import json
import time
import urllib.error
import urllib.request
from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from semantic_lint.diff import FilePatch, PullRequest

__all__ = [
    "CHECK_NAME",
    "MAX_SUMMARY_CHARS",
    "SUMMARY_MARKER",
    "Annotation",
    "CheckRun",
    "CheckRunOutput",
    "GitHub",
    "HttpError",
    "request_json",
]

API_URL: str = "https://api.github.com"
CHECK_NAME: str = "semantic-lint"
# The workflow's comment upsert finds the comment by this prefix and reads the
# finding count from it.
SUMMARY_MARKER: str = "<!-- semantic-lint:summary"
# GitHub rejects a check run summary longer than this.
MAX_SUMMARY_CHARS: int = 65535
RETRY_STATUSES: frozenset[int] = frozenset({429, 500, 502, 503, 504, 529})
MAX_ATTEMPTS: int = 5
FILES_PER_PAGE: int = 100
# GitHub lists at most 3,000 files for a pull request.
MAX_FILE_PAGES: int = 30


class Annotation(TypedDict):
    path: str
    start_line: int
    end_line: int
    annotation_level: Literal["notice", "warning"]
    title: str
    message: str


class CheckRunOutput(TypedDict):
    title: str
    summary: str
    annotations: list[Annotation]


class CheckRun(TypedDict):
    name: str
    head_sha: str
    status: Literal["completed"]
    # Advisory: never "failure".
    conclusion: Literal["success", "neutral"]
    output: CheckRunOutput


class HttpError(RuntimeError):
    def __init__(self, status: int, message: str) -> None:
        super().__init__(message)
        self.status: int = status


def request_json(
    url: str,
    method: str = "GET",
    headers: Mapping[str, str] | None = None,
    body: object | None = None,
    timeout: float = 60.0,
) -> Any:
    """Send one JSON request and return the parsed body, or None for an empty one.

    Retries RETRY_STATUSES and network errors with exponential backoff, then raises.
    """
    data = json.dumps(body).encode() if body is not None else None
    for attempt in range(MAX_ATTEMPTS):
        request = urllib.request.Request(  # noqa: S310
            url,
            data=data,
            method=method,
            headers={"Content-Type": "application/json", **(headers or {})},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                raw = response.read()
            return json.loads(raw) if raw else None
        except urllib.error.HTTPError as error:
            if error.code not in RETRY_STATUSES or attempt == MAX_ATTEMPTS - 1:
                detail = error.read()[:500].decode(errors="replace")
                raise HttpError(
                    error.code, f"{method} {url} returned {error.code}: {detail}"
                ) from error
            retry_after = error.headers.get("Retry-After", "")
            time.sleep(float(retry_after) if retry_after.isdigit() else 2**attempt)
        except (urllib.error.URLError, TimeoutError) as error:
            if attempt == MAX_ATTEMPTS - 1:
                raise RuntimeError(f"{method} {url} failed: {error}") from error
            time.sleep(2**attempt)
    raise AssertionError("unreachable")


class GitHub:
    """One repository on the GitHub REST API. Tests subclass it and override `request`."""

    def __init__(self, token: str, repo: str) -> None:
        self._token: str = token
        self.repo: str = repo

    def request(self, method: str, path: str, body: object | None = None) -> Any:
        return request_json(
            f"{API_URL}/repos/{self.repo}/{path}",
            method=method,
            headers={
                "Authorization": f"Bearer {self._token}",
                "Accept": "application/vnd.github+json",
                "X-GitHub-Api-Version": "2022-11-28",
            },
            body=body,
        )

    def head_sha(self, number: int) -> str:
        return str(self.request("GET", f"pulls/{number}")["head"]["sha"])

    def pull_request(self, number: int) -> PullRequest:
        pull = self.request("GET", f"pulls/{number}")
        files: list[FilePatch] = []
        for page in range(1, MAX_FILE_PAGES + 1):
            batch = self.request(
                "GET", f"pulls/{number}/files?per_page={FILES_PER_PAGE}&page={page}"
            )
            files.extend(
                FilePatch(item["filename"], item.get("patch")) for item in batch
            )
            if len(batch) < FILES_PER_PAGE:
                break
        return PullRequest(
            repo=self.repo,
            number=number,
            base_sha=str(pull["base"]["sha"]),
            head_sha=str(pull["head"]["sha"]),
            files=tuple(files),
        )

    def base_sha(self, number: int) -> str:
        return str(self.request("GET", f"pulls/{number}")["base"]["sha"])

    def compare(self, base: str, head: str) -> Any:
        """The compare payload trimmed to what eval caches."""
        payload = self.request("GET", f"compare/{base}...{head}")
        return {
            "status": payload["status"],
            "ahead_by": payload["ahead_by"],
            "files": [
                {
                    "filename": item["filename"],
                    "status": item["status"],
                    "patch": item.get("patch"),
                }
                for item in payload.get("files", [])
            ],
        }

    def review_comment(self, comment_id: int) -> Any | None:
        """A pull request review comment, or None when GitHub no longer has it."""
        try:
            return self.request("GET", f"pulls/comments/{comment_id}")
        except HttpError as error:
            if error.status == 404:
                return None
            raise

    def publish_check_run(self, number: int, check_run: CheckRun) -> bool:
        """Create the check run unless the PR head moved since the run began."""
        if self.head_sha(number) != check_run["head_sha"]:
            return False
        self.request("POST", "check-runs", check_run)
        return True
