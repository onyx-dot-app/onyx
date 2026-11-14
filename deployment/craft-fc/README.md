# Craft Firecracker artifacts

This directory builds the files that a Craft Firecracker host needs:

- `vmlinux`: the guest kernel, the Amazon Linux 2023 kernel 6.18 source with the
  Firecracker microVM config;
- `firecracker` and `jailer`: unmodified Firecracker release binaries.

The output is one OCI image, `onyxdotapp/craft-fc-artifacts:<kernel>-fc<firecracker>`
(for example `6.18.62-127.179-fc1.17.0`). The image is `FROM scratch` and is not
runnable. The host agent image (`microvm/Dockerfile`,
`onyxdotapp/craft-fc-host-agent`) copies its files to `/opt/craft-fc/`. Its
`ARTIFACTS_TAG` build arg must match the versions in `Dockerfile.artifacts`;
`.github/workflows/craft-fc-host-agent.yml` checks this.

## Image contents

| Path | What it is |
|---|---|
| `/craft-fc/vmlinux` | Uncompressed x86_64 guest kernel |
| `/craft-fc/vmlinux.config` | The full kernel config used for the build |
| `/craft-fc/firecracker`, `/craft-fc/jailer` | Firecracker release binaries |
| `/craft-fc/SOURCE.md` | Kernel source tag, commit, config inputs and our config fragment |
| `/craft-fc/licenses/linux/` | GPL-2.0 license text |
| `/craft-fc/licenses/firecracker/` | Apache-2.0 `LICENSE`, `NOTICE` and `THIRD-PARTY` |

## Inputs

All versions and hashes are `ARG` values at the top of `Dockerfile.artifacts`:

- Kernel source: tag `kernel6.18-6.18.62-127.179.amzn2023` of
  `github.com/amazonlinux/linux`, the source of the AL2023 `kernel6.18` package.
  The build fails if the tag does not point to the pinned commit.
- Base config: `resources/guest_configs/microvm-kernel-ci-x86_64-6.18.config` from
  Firecracker `v1.17.0`, pinned by SHA256.
- Our changes: `kernel/config-fragment`. The build fails if a line of the
  fragment is not in the final `.config`.
- Firecracker `v1.17.0`: the build checks the release tarball against a pinned
  SHA256 and the release's `.sha256.txt`. Then it checks each file against the
  `SHA256SUMS` file in the tarball.

The config fragment has three changes:

1. `CONFIG_CRYPTO_FIPS140_EXTMOD` off. With the stock config, a self-built kernel
   panics at boot in the FIPS140 module loader.
2. `CONFIG_CGROUP_MISC` on.
3. `CONFIG_IKCONFIG` and `CONFIG_IKCONFIG_PROC` on, so the guest shows its config
   at `/proc/config.gz`.

## Build locally

The builder stage runs on your machine's platform. On arm64 it cross-compiles
for x86_64.

```bash
cd deployment/craft-fc
docker buildx build --platform linux/amd64 -f Dockerfile.artifacts \
  --target artifacts --output type=local,dest=/tmp/craft-fc-out .
./check-artifacts.sh /tmp/craft-fc-out
```

`check-artifacts.sh` downloads the Firecracker release again and compares the
binaries with its `SHA256SUMS`. It also checks the vmlinux ELF header, the
kernel release (`6.18.62`, with no `+`), the license files and the config
fragment.

## CI and publishing

`.github/workflows/craft-fc-artifacts.yml` runs on pull requests and pushes to
`main` that change this directory or the workflow. Those runs build and check
the image. They do not push it.

To publish, run the workflow manually on `main`. The publish job:

- uses the `release` environment and the Docker Hub credentials that
  `deployment.yml` uses;
- stops if either tag already exists, or if it cannot tell. A published tag
  never changes;
- pushes both images by digest only, with no tag;
- pulls those digests and runs the same checks on them;
- tags the checked digests: `<tag>-source` first, then `<tag>`.

If you change `kernel/config-fragment` but not the versions, set the `revision`
input (for example `r2`). The tag then becomes `<tag>-r2`.

## GPL-2.0 source obligation

The guest kernel is GPL-2.0. Each published `vmlinux` must have its complete
corresponding source next to it. The publish job tags the source as the
`<tag>-source` image before it tags the binary. That image has:

- `linux-<kernel tag>.tar.xz`, a `git archive` of the pinned commit;
- `fc-base.config` and `config-fragment`;
- `build/`: `Dockerfile.artifacts`, `check-artifacts.sh` and the fragment;
- `SOURCE.md`, with a link to the onyx commit that built the image.

Do not copy `vmlinux` to another registry, bucket or release page without its
`-source` image or an equivalent copy of the source.

## Change a version

1. Change the `ARG` values in `Dockerfile.artifacts`. Update every matching
   SHA256 and the kernel commit. For the kernel, use the newest tag of the series
   in `amazonlinux/linux`: a `kernel6.18-<version>` tag (the AL2023 package
   source, released with each kernel advisory) or a `microvm-kernel` tag, if one
   is newer. List them with
   `git ls-remote --tags https://github.com/amazonlinux/linux.git 'refs/tags/*kernel*6.18*'`.
   `KERNEL_COMMIT` is the commit of the tag (the `^{}` line for an annotated tag).
   Set `ARTIFACTS_TAG` in `microvm/Dockerfile` to the new tag.
2. Build locally and run `check-artifacts.sh`.
3. Do a boot test on a KVM host. See below.
4. Merge, then run the workflow on `main` to publish.

## Boot test

The CI build does not boot the kernel, because CI runners have no `/dev/kvm`.
Before you publish a new kernel, boot it on a KVM host: an Intel `.metal`
instance, or a `c8i`/`m8i`/`r8i` instance with nested virtualization.

1. Copy `vmlinux`, `firecracker` and `jailer` from the image to the host.
2. Start a microVM with `firecracker --no-api --config-file vm.json`. In
   `vm.json`, set `boot-source.kernel_image_path` to this `vmlinux` and
   `boot_args` to `console=ttyS0 reboot=k panic=1`. Use an ext4 root drive with
   an init that you can log in to or that prints to the console.
3. In the guest, check:
   - `uname -r` prints the kernel release of `KERNEL_TAG` (for example `6.18.62`);
   - `zcat /proc/config.gz` has every line of `kernel/config-fragment`;
   - `misc` is in `/proc/cgroups`;
   - the console shows no `panic`, `Oops` or `BUG`.
4. After a Firecracker version change, also create a snapshot of a running
   microVM and restore it.
