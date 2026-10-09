# OneDrive daily test

Read-only tests use the fixed `danswerai` tenant corpus. CI does not modify this
corpus.

The test uses these existing certificate-app variables:

- `PERM_SYNC_SHAREPOINT_CLIENT_ID`
- `PERM_SYNC_SHAREPOINT_DIRECTORY_ID`
- `PERM_SYNC_SHAREPOINT_PRIVATE_KEY`
- `PERM_SYNC_SHAREPOINT_CERTIFICATE_PASSWORD`

Run the test from the repository root:

```bash
uv run --env-file .vscode/.env pytest \
  backend/tests/daily/connectors/onedrive/test_onedrive_fixed_tenant_daily.py
```
