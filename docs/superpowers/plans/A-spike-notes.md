# Glomi Forge Daytona Spike Notes

Date: 2026-06-23

## Status

Spike pending. This machine does not currently have a local Daytona control plane or `DAYTONA_API_URL` configured, so the live SDK verification still needs to be filled in after Daytona is available.

## Initial SDK Shape From Plan

The implementation plan currently expects this Python SDK shape:

```python
from daytona import Daytona, DaytonaConfig, CreateSandboxFromSnapshotParams

d = Daytona(DaytonaConfig(api_key="...", api_url="http://localhost:..."))
sb = d.create(CreateSandboxFromSnapshotParams(snapshot="daytona", language="python"))
sb.fs.upload_file(b"hello", "/workspace/hello.txt")
print(sb.process.exec("cat /workspace/hello.txt").result)
sb.public = True
print(sb.get_preview_link(3000).url)
d.delete(sb)
```

## Values To Verify Later

- SDK method signatures for `Daytona`, `DaytonaConfig`, and `CreateSandboxFromSnapshotParams`.
- Return fields for `create`, `process.exec`, `fs.upload_file`, `get_preview_link`, `delete`, and `stop`.
- Whether preview exposure needs `sb.public = True`, a Daytona API call, or a sandbox metadata update.
- Preview URL format for local OSS Daytona.
- Local endpoint and authentication flow used by the OSS docker-compose deployment.

## Notes

- `uv add daytona --no-sync` resolved `daytona>=0.189.0` and updated the root `pyproject.toml`/`uv.lock`.
- A plain `uv add daytona` attempted to sync and failed on this macOS x86_64 machine because the resolved `torch==2.9.1` package has no matching wheel for this platform. This is an environment sync limitation, not a Daytona resolution failure.
