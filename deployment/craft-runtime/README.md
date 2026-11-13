# Craft runtime userspace image

`onyxdotapp/craft-runtime` supplies execution tools and assets for the new integrated Onyx harness.
Existing Craft does not use this image.
It includes Python, Node, document tools, Chrome, Xvfb, and command-line tools.
It contains no agent, guest daemon, VM init, deployment CA, or user data.

The current pod and Docker backends continue to use `onyxdotapp/sandbox`.
This change does not change `SANDBOX_RUNTIME`, Helm image settings, or their default values.

## Build and check the userspace image

Run from the repository root:

```bash
docker buildx bake -f deployment/craft-runtime/docker-bake.hcl --load runtime
docker run --rm --platform linux/amd64 --network none --shm-size=256m \
  --security-opt seccomp=unconfined \
  onyxdotapp/craft-runtime:dev /opt/onyx/check-runtime
```

The container check creates DOCX, XLSX, charts, and presentations, then converts Office files to PDF.
It renders both baked SVG icon sets and tests headful Chrome on Xvfb, without network access.
Chromium's namespace sandbox needs the container check's seccomp setting.
This check does not boot Firecracker.

`docker-bake.hcl` defines the base image references, tool versions, and build defaults.
Environment variables override those values.
Use `--set runtime.secret=id=build_ca_bundle,src=/path/to/ca-bundle.crt` for a custom build CA.
The shared sandbox `install-browser.sh` installs Chrome and writes its vulnerability inventory.
It uses the same Chrome pin as the sandbox image, so `update-sandbox-browser.yml` updates both.
The runtime workflows audit that browser's inventory through ODS before publishing.

Python dependencies have a separate hash-checked lock.
Refresh it with:

```bash
uv pip compile deployment/craft-runtime/requirements.in \
  --python-version 3.13 --python-platform linux --generate-hashes \
  --output-file deployment/craft-runtime/requirements.txt
```

The Python environment is `/opt/onyx/python`, on `PATH`.
`NODE_PATH` exposes global JavaScript modules.
Lucide and Tabler SVGs and license files are under `/opt/onyx/assets/icons/`.
Their npm packages do not ship in the final image.
New harness skill scripts must read these asset paths directly.
The `sandbox` user, UID 1000, supplies the browser home and Chromium NSS database.
Agent commands run as root. The default container command is Bash.

## Convert the image with the existing rootfs builder

The image is an input to `deployment/craft-fc/rootfs/build-rootfs.sh`.
Do not deploy it as the host-agent image or extract it directly into a VM disk.
Docker export loses image environment variables; the converter preserves them in `guest.env`.

On a Linux x86-64 host, build the existing Go binaries and convert a published runtime image:

```bash
(cd microvm && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
  go build -trimpath -o ../out/guest-daemon ./cmd/guest-daemon)
(cd microvm && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
  go build -trimpath -o ../out/egress-relay ./cmd/egress-relay)
sudo bash deployment/craft-fc/rootfs/build-rootfs.sh \
  --image onyxdotapp/craft-runtime:v5.2.0 \
  --daemon-bin out/guest-daemon --relay-bin out/egress-relay \
  --out out/rootfs
```

Use the Onyx release tag required by your deployment instead of the example tag.
The command makes a root drive with no egress CA. The guest daemon installs the deployment CA at `Init`.
See `../craft-fc/rootfs/README.md` for host requirements, the optional `--ca`, and the drive layout.

| Component | Owner and output |
|---|---|
| Userspace tools and assets | This image, versioned with the Onyx application |
| Guest daemon and Go relay | `microvm/cmd/guest-daemon` and `microvm/cmd/egress-relay` |
| Init, overlays, proxy settings | Existing rootfs converter, producing `rootfs.ext4` and `manifest.json` |
| Deployment egress CA | The host agent sends it with `SetKey`; the guest daemon installs it at `Init` |
| VM creation, identity, mTLS, guest gRPC pass-through | `microvm` host agent, published separately as `craft-fc-host-agent` |
| Kernel, Firecracker, jailer | `craft-fc-artifacts` |

The converter installs supervised services under `/craft-fc`, outside writable overlays.
It configures the daemon on vsock port 52 and the guest proxy on `127.0.0.1:3128`.
Rootfs compatibility comes from its manifest, not a separate runtime protocol file.

The node template work consumes the converter's disk files and manifest, not this OCI image directly.
`.github/workflows/craft-fc-rootfs.yml` converts a tag of this image and publishes the files as
`onyxdotapp/craft-fc-artifacts:rootfs-<version>`. The Helm chart copies them to each node
(`craft.hostAgent.rootfs`, see `../craft-fc/rootfs/README.md`).

## Check rootfs conversion

On a Linux host with Docker, Go, and the rootfs build tools installed, run:

```bash
sudo env "PATH=$PATH" bash deployment/craft-runtime/check-rootfs.sh onyxdotapp/craft-runtime:dev
```

The check builds the real guest daemon and relay from `microvm/`.
It creates a loopback registry, then calls the existing rootfs converter with no `--ca`.
It checks the ext4 hash, embedded programs, preserved environment, ports, the CA-free manifest, and the managed-drive layout.
It removes the test registry, rootfs output, and temporary image tag when it exits.
This validates conversion without KVM; it does not test VM boot, mTLS routing, or snapshot restore.

## Verify the image inside Firecracker

The image workflows use an Intel m8i nested-KVM runner with an 80 GB root disk.
They build the pinned kernel and Firecracker from `Dockerfile.artifacts`, then run
`check-kvm.sh`. Both container smoke and real VM smoke must pass before publishing.
The rootfs converter needs space for Docker layers, the exported tree, and the ext4 disk.

For a complete local check on a prepared Linux x86-64 KVM host:

```bash
sudo env "PATH=$PATH" bash deployment/craft-runtime/check-kvm.sh \
  onyxdotapp/craft-runtime:dev /path/to/craft-fc-artifacts/craft-fc
```

The script converts the image, creates scratch/managed disks, and runs daemon,
init, restore, and image-tool checks. It cleans up its own VM files afterward.


Container smoke checks and rootfs conversion do not prove the tools work inside a VM.
Use an x86-64 Linux KVM host for the published image and its 6.18 guest kernel.
Prepare `KVM_IMG_DIR` with `vmlinux`, the converted `rootfs.ext4`, a 1 GiB ext4
`scratch-empty.ext4`, and an empty ext4 `managed-empty.ext4`.
The kernel and Firecracker binary come from `craft-fc-artifacts`.

Keep the image and work directories on the same filesystem; the fixtures hard-link disks.
Use a dedicated work directory, since tests replace their per-VM subdirectories.
Compile the suite from the repository root:

```bash
mkdir -p out
(cd microvm && CGO_ENABLED=0 GOOS=linux GOARCH=amd64 \
  go test -c -tags kvm -o ../out/craft-runtime-kvm.test ./internal/guestd/kvmtest)
sudo env KVM_RUNTIME_IMAGE=1 \
  KVM_FC_BIN=/path/to/firecracker KVM_IMG_DIR=/path/to/kvm-images \
  KVM_WORK_DIR=/var/tmp/craft-runtime-kvm \
  out/craft-runtime-kvm.test -test.v -test.run '^TestRuntimeImageKVM$'
```

`KVM_RUNTIME_IMAGE=1` selects the new image check. Without it, the generic daemon
suite leaves this check disabled so legacy sandbox rootfs fixtures remain usable.
With it enabled, a missing or failing runtime smoke command fails the test.
Interrupted commands retain partial output for diagnosis.
ARM64 Lima runs use a test-only image variant; they do not validate the published x86-64 artifact.

## Skills and user state

Skills and other managed content arrive on read-only drives: `/mnt/skills`, `/mnt/user-uploads` and `/mnt/spaces`.
Managed drives use `noexec`; invoke scripts through interpreters, such as `node icon.js` or `python script.py`.
The managed-drive hot-swap work owns updates to these files.
The rootfs converter makes the mount points and `/home/onyx/workspaces`, the parent of the session directories.
This image does not install or synchronize skill bundles.

The rootfs converter owns scratch overlays for `/etc`, `/home`, `/root`, `/opt`, `/srv`, `/usr`, `/var`, and `/workspace`.
It makes the sandbox user's empty NSS database. The guest daemon adds the proxy CA to it at `Init`.
Browser management and file/session APIs are separate guest-daemon features; this image does not implement them.

## Harness-owned operations

Company search and image generation belong to the integrated harness.
The image does not include `onyx-cli`, provider SDKs for those operations, or their credentials.
The harness can reuse Onyx's server-side image-generation tool and file store.
It must transfer reference images from the VM before generation when needed.
It must copy generated images into the session workspace when scripts need local files.
These harness tools and file transfers are integration work, not implemented by this image.

The image creates no `user_library` or fixed `attachments/` directory.
The harness places files needed by commands into the session workspace through the guest file interface.
Published artifacts remain in the file store and do not require a running VM.
The image has no runtime capability manifest; the OCI version label and rootfs manifest identify the build.

## Release versioning

The runtime uses the Onyx application release tag and the same release routing as the existing sandbox image.
A separate tag-triggered workflow calls the same `ods release classify` command as the application pipeline.
Stable semver aliases, beta, edge, latest, and their `-dev` aliases follow those classification results.
A runtime release failure does not block the existing pod/Docker deployment workflow.
It has no independent release version. The host-agent image keeps its existing separate versioning.
Release checks and audits run before publication. Existing pod/Docker deployment settings stay unchanged.
