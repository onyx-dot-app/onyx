# Output Contract

On success, write `/workspace/out/output_manifest.json`:

```json
{
  "artifact_version": 1,
  "primary_artifact_path": "/workspace/src",
  "primary_artifact_type": "landing_page",
  "preview_entry": { "url": "", "port": 3000, "route": "/" },
  "files": [{ "path": "/workspace/src/app/page.tsx", "kind": "source" }],
  "notes": []
}
```
