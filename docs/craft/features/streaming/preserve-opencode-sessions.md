# Preserve OpenCode session history

OpenCode history is sandbox-global state. It lives outside one BuildSession's
outputs and attachments, so normal session snapshots do not fully describe it.

Current flow:

1. Before recovery or idle termination, the api_server asks the sandbox guest
   helper to package OpenCode history.
2. The helper reads the pod-local data from the main sandbox container.
3. The api_server stores the archive in FileStore.
4. On the next sandbox boot, the helper restores the archive before
   `opencode serve` becomes ready.

There is no sidecar endpoint or push daemon in this flow. Transport is
Kubernetes `exec` to:

```text
/opt/onyx-guest/venv/bin/python -I -m onyx_guest
```

Keep the flow fail-closed. If a live history snapshot cannot be taken, recovery
must preserve the older stored history rather than overwrite it with an empty
archive. If restored current history is corrupt, the helper may clear the live
store so OpenCode can start, but it must not silently delete the stored archive.

Verify with a real sandbox flow:

- create a Craft session
- send turns that create OpenCode history
- snapshot history
- terminate and recreate the sandbox
- confirm history is available after `opencode serve` is ready
