"""Points Onyx's Google connectors at the mock Drive server. Test code only:
Onyx has no setting for this.

It patches four things:

- the Google client builder, so every API client (and its batch requests)
  uses the mock's URL as the discovery document's root URL;
- the token endpoint of service account keys (Onyx sets Google's);
- the token endpoint of OAuth credentials (the Google library sets Google's);
- the Docs and Forms API URLs, which the Drive connector calls without a
  client.

In a test, use ``point_onyx_at_mock`` as a context manager. For a running
Onyx, ``sitecustomize.py`` in the parent directory calls
``install_for_process`` when ``MOCK_GDRIVE_URL`` is set.

This module imports Onyx only inside its functions, so a process can load it
before Onyx.
"""

import importlib
import importlib.abc
import importlib.machinery
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import ExitStack, contextmanager
from types import ModuleType
from typing import Any
from unittest import mock

# Module name -> a function that gives the attributes to set on that module.
type _ModulePatch = Callable[[ModuleType], dict[str, object]]


def _base(url: str) -> str:
    return url if url.endswith("/") else f"{url}/"


class _RedirectedBuilder:
    """Google's ``build_from_document`` with the mock as the root URL."""

    def __init__(self, current: Callable[..., Any], base: str) -> None:
        # Wrap Google's builder, not an earlier redirect, so the newest patch
        # selects the URL.
        self.original: Callable[..., Any] = (
            current.original if isinstance(current, _RedirectedBuilder) else current
        )
        self.base = base

    def __call__(self, service: Any, *args: Any, **kwargs: Any) -> Any:
        if isinstance(service, bytes):
            service = service.decode("utf-8")
        doc = json.loads(service) if isinstance(service, str) else dict(service)
        # Batch requests read the root URL from the document, so an
        # api_endpoint client option would not move them.
        doc["rootUrl"] = self.base
        doc["mtlsRootUrl"] = self.base
        return self.original(doc, *args, **kwargs)


def _module_patches(base: str) -> dict[str, _ModulePatch]:
    token_uri = f"{base}token"

    def client_builder(module: ModuleType) -> dict[str, object]:
        return {
            "build_from_document": _RedirectedBuilder(module.build_from_document, base)
        }

    def oauth_token_endpoint(_module: ModuleType) -> dict[str, object]:
        return {"_GOOGLE_OAUTH2_TOKEN_ENDPOINT": token_uri}

    def service_account_token_endpoint(_module: ModuleType) -> dict[str, object]:
        return {"GOOGLE_TOKEN_URI": token_uri}

    def docs_and_forms(_module: ModuleType) -> dict[str, object]:
        return {
            "_DOCS_API_DOCUMENT_URL": base + "v1/documents/{doc_id}",
            "_FORMS_API_FORM_URL": base + "v1/forms/{form_id}",
        }

    return {
        "googleapiclient.discovery": client_builder,
        "google.oauth2.credentials": oauth_token_endpoint,
        "onyx.connectors.google_utils.google_auth": service_account_token_endpoint,
        "onyx.connectors.google_drive.source_operations": docs_and_forms,
    }


@contextmanager
def point_onyx_at_mock(mock_url: str) -> Iterator[None]:
    """Sends the Google calls of this process to the mock at ``mock_url``
    until the block ends. Imports the patched Onyx modules."""
    with ExitStack() as stack:
        for module_name, patch in _module_patches(_base(mock_url)).items():
            module = importlib.import_module(module_name)
            for name, value in patch(module).items():
                stack.enter_context(mock.patch.object(module, name, value))
        yield


class _PatchOnImport(importlib.abc.MetaPathFinder):
    """Patches a module right after its first import."""

    def __init__(self, patches: dict[str, _ModulePatch]) -> None:
        self._patches = patches

    def find_spec(
        self,
        fullname: str,
        path: Sequence[str] | None,
        target: ModuleType | None = None,
    ) -> importlib.machinery.ModuleSpec | None:
        # Keep the patch until the module runs: a find_spec probe does not
        # always import the module.
        patch = self._patches.get(fullname)
        if patch is None:
            return None
        spec = None
        for finder in sys.meta_path:
            if finder is self:
                continue
            spec = finder.find_spec(fullname, path, target)
            if spec is not None:
                break
        if spec is None or spec.loader is None:
            return spec
        loader = spec.loader
        exec_module = loader.exec_module

        def exec_and_patch(module: ModuleType) -> None:
            exec_module(module)
            for name, value in patch(module).items():
                setattr(module, name, value)
            self._patches.pop(fullname, None)

        loader.exec_module = exec_and_patch  # ty: ignore[invalid-assignment]
        return spec


def install_for_process(mock_url: str) -> None:
    """Sends the Google calls of this process to the mock for its whole life.
    A module that is not imported yet is patched when it is."""
    pending: dict[str, _ModulePatch] = {}
    for module_name, patch in _module_patches(_base(mock_url)).items():
        module = sys.modules.get(module_name)
        if module is None:
            pending[module_name] = patch
            continue
        for name, value in patch(module).items():
            setattr(module, name, value)
    if pending:
        sys.meta_path.insert(0, _PatchOnImport(pending))
