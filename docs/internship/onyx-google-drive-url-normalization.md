# Onyx Internship Investigation: Google Drive URL Resolution

## Scope

This investigation follows a Google Drive URL from the `open_url` tool to the indexed document lookup.
The focused change is in `GoogleDriveConnector.normalize_url`.

## End-to-end flow

1. The `open_url` tool receives one or more URLs.
2. `_resolve_urls_to_document_ids` calls `normalize_url_candidates`.
3. `normalize_url_candidates` detects Google Drive URLs and dispatches to `GoogleDriveConnector.normalize_url`.
4. The connector extracts the Drive file ID from either `?id=` or a `/d/<id>` path.
5. Google Drive file IDs do not always reveal whether the source is a Doc, Sheet, Slide, or uploaded binary file. The connector returns a best normalized ID plus candidate canonical IDs for all supported forms.
6. The resolver expands URL variants and queries the database for existing indexed document IDs. The first matching candidate is used to open the document.

During ingestion, `doc_conversion.py` and the Google Drive retrieval code produce the canonical web-view identifiers. The normalization logic must therefore match those identifiers exactly.

## Bug found

The connector checked the parsed network location with:

```python
netloc.startswith(("docs.google.com", "drive.google.com"))
```

This accepted attacker-controlled hostnames such as `docs.google.com.evil.com`. A URL with that host could be treated as a Google Drive URL and converted into a real-looking Drive document identifier. The same prefix mistake also accepted subdomains such as `foo.docs.google.com`.

Malformed bracketed hosts were another edge case: `urlparse` can raise `ValueError`, which should not escape from a URL normalizer handling user or model-provided input.

## Change made

`GoogleDriveConnector.normalize_url` now:

- Parses the URL inside a `ValueError` guard.
- Accepts only the exact hostnames `docs.google.com` and `drive.google.com`.
- Returns an unsuccessful `NormalizationResult` for spoofed, unrelated, or malformed hosts.
- Keeps the existing canonicalization and candidate-ID behavior unchanged.

Regression coverage includes canonical Docs, Sheets, Slides, Drive file, multi-account, and `?id=` URLs, spoofed domains, subdomains, unrelated hosts, missing IDs, and malformed hosts.

## Validation

The two touched Python files pass `py_compile`.

The focused pytest command is:

```text
uv run pytest -q backend/tests/unit/onyx/connectors/google_drive/test_drive_url_normalization.py
```

It could not collect in the current Windows environment because the pinned `chonkie` dependency requires Microsoft Visual C++ 14.0 or newer during installation. A lightweight environment also lacked the backend dependency `fastapi_users`. Install the repository dependencies with the project-supported toolchain and rerun the command before opening the pull request.

## Video outline

1. State the scope: Google Drive URL normalization and `open_url` resolution.
2. Show `_resolve_urls_to_document_ids` and `normalize_url_candidates`.
3. Show `GoogleDriveConnector.normalize_url` and explain candidate IDs.
4. Demonstrate why prefix matching accepts `docs.google.com.evil.com`.
5. Show the exact-hostname fix and malformed-input guard.
6. Run the focused pytest command and explain any local dependency blocker.
7. Show the final diff and summarize the security impact and regression tests.
