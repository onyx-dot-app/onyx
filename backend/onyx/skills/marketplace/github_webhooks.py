"""GitHub webhook transport used only by the marketplace provider adapter."""

from typing import Literal
from urllib.parse import quote

import requests
from pydantic import TypeAdapter, ValidationError

from onyx.error_handling.error_codes import OnyxErrorCode
from onyx.error_handling.exceptions import OnyxError
from onyx.skills.marketplace.models import (
    GitHubHook,
    GitHubMarketplaceConfig,
    GitHubRef,
    GitHubRepository,
)
from onyx.utils.github import GITHUB_COMMIT_SHA_PATTERN


class GitHubWebhooks:
    def __init__(self, config: GitHubMarketplaceConfig, authorization: str) -> None:
        self.config = config
        self.headers = {
            "Authorization": authorization,
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }
        self.url = (
            "https://api.github.com/repos/"
            f"{quote(config.owner, safe='')}/{quote(config.repo, safe='')}"
        )

    def _request(
        self,
        method: Literal["GET", "POST", "PATCH", "DELETE"],
        path: str,
        *,
        body: dict[str, object] | None = None,
        allowed: tuple[int, ...] = (),
    ) -> requests.Response:
        try:
            response = requests.request(
                method,
                self.url + path,
                headers=self.headers,
                json=body,
                timeout=30,
                allow_redirects=False,
            )
        except requests.RequestException as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "Could not reach GitHub. Retry webhook setup; Sync now remains available.",
            ) from exc
        if response.status_code in (200, 201, 204, *allowed):
            return response
        status = response.status_code
        rate_limited = status == 429 or (
            status == 403
            and (
                response.headers.get("X-RateLimit-Remaining") == "0"
                or "Retry-After" in response.headers
            )
        )
        response.close()
        if rate_limited:
            raise OnyxError(
                OnyxErrorCode.RATE_LIMITED,
                "GitHub rate limit reached. Try again later.",
            )
        if status == 401:
            raise OnyxError(
                OnyxErrorCode.UNAUTHENTICATED,
                "Reconnect the marketplace's GitHub login, then retry webhook setup.",
            )
        if status in {403, 404}:
            raise OnyxError(
                OnyxErrorCode.INSUFFICIENT_PERMISSIONS,
                "GitHub denied webhook access. Use a repository admin login with webhook permission and authorize organization SSO if required.",
            )
        if status == 422:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "GitHub rejected webhook setup. Check the public callback URL and repository webhook settings.",
            )
        raise OnyxError(
            OnyxErrorCode.BAD_GATEWAY,
            "GitHub could not configure the webhook. Try again; Sync now remains available.",
        )

    def resolve_ref(self) -> str:
        ref = self.config.ref
        if GITHUB_COMMIT_SHA_PATTERN.fullmatch(ref):
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Pinned commits cannot receive push updates. Use a branch or tag.",
            )
        try:
            if ref == "HEAD":
                with self._request("GET", "") as response:
                    ref = (
                        "refs/heads/"
                        + GitHubRepository.model_validate_json(
                            response.content
                        ).default_branch
                    )
            candidates = (
                [ref]
                if ref.startswith("refs/")
                else [f"refs/heads/{ref}", f"refs/tags/{ref}"]
            )
            found: list[str] = []
            for candidate in candidates:
                if not candidate.startswith(("refs/heads/", "refs/tags/")):
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "Push updates require a branch or tag ref.",
                    )
                with self._request(
                    "GET",
                    "/git/ref/" + quote(candidate.removeprefix("refs/"), safe="/"),
                    allowed=(404,),
                ) as response:
                    if response.status_code == 404:
                        continue
                    actual = GitHubRef.model_validate_json(response.content).ref
                    if actual != candidate:
                        raise ValueError("Unexpected GitHub ref")
                    found.append(actual)
        except (ValidationError, ValueError) as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY, "GitHub returned an invalid branch or tag."
            ) from exc
        if len(found) != 1:
            raise OnyxError(
                OnyxErrorCode.INVALID_INPUT,
                "Choose an existing, unambiguous branch or tag. Use refs/heads/ or refs/tags/ when names overlap.",
            )
        return found[0]

    def _find(self, callback_url: str) -> int | None:
        matching: list[int] = []
        for page in range(1, 11):
            with self._request("GET", f"/hooks?per_page=100&page={page}") as response:
                hooks = TypeAdapter(list[GitHubHook]).validate_json(response.content)
            matching.extend(
                hook.id for hook in hooks if hook.config.url == callback_url
            )
            if len(matching) > 1:
                raise OnyxError(
                    OnyxErrorCode.CONFLICT,
                    "Multiple GitHub hooks use this callback. Remove duplicates in repository settings.",
                )
            if len(hooks) < 100:
                return matching[0] if matching else None
        raise OnyxError(
            OnyxErrorCode.INVALID_INPUT,
            "Too many GitHub webhooks to inspect. Review the repository webhook settings.",
        )

    def ensure(self, callback_url: str, secret: str) -> str:
        body: dict[str, object] = {
            "name": "web",
            "active": True,
            "events": ["push"],
            "config": {
                "url": callback_url,
                "content_type": "json",
                "secret": secret,
                "insecure_ssl": "0",
            },
        }
        try:
            hook_id = self._find(callback_url)
            if hook_id is None:
                with self._request(
                    "POST", "/hooks", body=body, allowed=(422,)
                ) as response:
                    if response.status_code != 422:
                        return str(GitHubHook.model_validate_json(response.content).id)
                # Another setup request, or a lost acknowledgement, may have created it.
                hook_id = self._find(callback_url)
                if hook_id is None:
                    raise OnyxError(
                        OnyxErrorCode.INVALID_INPUT,
                        "GitHub rejected webhook setup. Check the callback URL and repository webhook settings.",
                    )
            with self._request("PATCH", f"/hooks/{hook_id}", body=body) as response:
                return str(GitHubHook.model_validate_json(response.content).id)
        except ValidationError as exc:
            raise OnyxError(
                OnyxErrorCode.BAD_GATEWAY,
                "GitHub returned an invalid webhook response.",
            ) from exc

    def remove(self, hook_id: str) -> None:
        if not hook_id.isdecimal():
            raise OnyxError(OnyxErrorCode.INVALID_INPUT, "Invalid GitHub webhook ID.")
        with self._request("DELETE", f"/hooks/{hook_id}", allowed=(404,)):
            pass
