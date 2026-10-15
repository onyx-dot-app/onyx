# Craft guest image

The image runs inside the mandatory Kata Firecracker RuntimeClass. Each user gets
one VM and one long-lived container. Session directories share that VM.

A short init container locks both IP address families to proxy-only egress.
The root supervisor installs the proxy CA, publishes bootstrap status, and waits for history restore.
OpenCode starts as UID 1000 after the root-only history gate opens. The agent has
no capabilities or supplementary groups and cannot gain privileges through exec.
The main container has no network administration capability. A user supervisor
forwards termination signals and reaps child processes without an added dependency.

## Build

```bash
cd backend/onyx/server/features/build/sandbox/image
docker build -t onyxdotapp/sandbox:firecracker-v2 .
```

Use `--platform linux/amd64` or `--platform linux/arm64` to match the sandbox node.
`ENABLE_SKILLS=false` omits office tools and fonts. `ENABLE_BROWSER=false` omits
Chromium and the browser CLI. Neither switch changes the guest security boundary.

Release CI gives the sandbox image the same tag as the application image. It also
publishes a content tag for this build context. Deploy matching application and
sandbox releases. Use Helm sandbox image values for local test image overrides.

## Guest command

The API uses Kubernetes exec through Kata's guest agent. There is no HTTP helper.

```text
/opt/onyx-guest/venv/bin/python -I -m onyx_guest OPERATION METADATA_JSON
```

The image installs `guest/` as `onyx_guest` in its own root-owned interpreter.
The package, interpreter, boot scripts, and ancestor directories are immutable
to UID 1000. Python isolated mode ignores workspace modules and Python environment
settings. Root code never imports from the agent's Python environment or templates.

Small typed fields travel in the JSON argument. File bytes, scripts, and archives
travel on attached stdin. Read operations leave stdin detached. Payload operations
consume it before returning metadata; `run` uses `has_stdin` to make this choice explicit. Metadata
operations emit JSON. Reads and snapshots emit raw bytes. Empty snapshot output
means there was no content. Errors emit bounded stderr and exit with a nonzero code.

Root operations are `serve`, `status`, `push-managed`, `restore-history`, and
`release-history`. All other operations drop to UID 1000 before accessing files
or executing commands. History restore holds a root lock while a user child
extracts the archive. Only successful extraction opens the startup gate.

## Filesystem

`/workspace` and `/workspace/managed` are root-owned with mode 0755. Managed
skills, user libraries, and document preview bundles publish through atomic
symlink swaps. Publication prunes unused versions after a 60-second reader grace
period. Root never executes code from these bundles.

The writable container root filesystem holds sessions, OpenCode history, the user
home, caches, and temporary files. These paths belong to UID 1000. Only the proxy
CA uses a projected read-only mount. Container removal destroys writable state.
The API stores session and history archives in FileStore before normal removal.

The image preserves the existing output and attachment archive layout. Bun's
prewarmed cache rebuilds excluded dependencies after restore. Global OpenCode
configuration directories hardlink template dependencies. Session dependency
copies remain independent. Templates and the agent's Python environment remain
user-writable because only user processes execute them.

OpenCode listens on port 4096. Generated previews use allocated session ports.
Readiness checks use TCP 4096 after the API releases the history gate.
