# OneDrive daily test

This test uses the fixed `danswerai` tenant corpus. Its fixture utility owns only
the `Onyx OneDrive Daily Tests` subtree in two test drives.

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

The test resets the daily corpus before mutation coverage. It resets the same
corpus during teardown, even when a mutation assertion fails. Do not point the
owner variables at drives where this subtree contains user data.
