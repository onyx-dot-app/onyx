"""Tenant-scoped allowlist for sidecar snapshot egress.

The pod-wide iptables lockdown forces ALL egress through this proxy,
and the gate's 1 MiB body cap fail-closes any oversize request body.
That cap is correct for the agent's external-app calls (the only thing
the matcher inspects), but it also catches the sidecar's snapshot
upload — `tar -czf - | s5cmd pipe s3://...` — whose multipart parts
run well past 1 MiB. Buffering those parts into the shared proxy's
memory is also a DoS surface.

This policy decides, per request, whether a flow is a snapshot upload
to the configured bucket under the *resolving tenant's* own snapshot
prefix. When it is, the gate streams the body through unbuffered
(`flow.request.stream = True`) instead of capping it. The scope is
deliberately narrow:

* exact endpoint host (custom S3 endpoint / MinIO) or the bucket's
  virtual-hosted AWS subdomain — never a broad `*.amazonaws.com`
  suffix, so a request to an attacker-controlled bucket/host doesn't
  match.
* the key must live under `{tenant_id}/snapshots/...`, where
  `tenant_id` is the tenant resolved from the source pod IP — so a
  prompt-injected agent can't stream uncapped to another tenant's
  prefix (the live concern on a shared path-style MinIO, where every
  bucket shares one host) or to an arbitrary key.

Header/path/host stay inspectable at `requestheaders` time; only the
opaque `tar.gz` body is left unbuffered.

Key layout mirrors `sandbox_daemon/snapshot.py`:
`{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz` in
`SANDBOX_S3_BUCKET`.
"""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from onyx.server.features.build.configs import SANDBOX_S3_BUCKET

_SNAPSHOTS_SEGMENT = "snapshots"


@dataclass(frozen=True)
class SnapshotEgressPolicy:
    """Decides whether a flow is snapshot egress to the tenant's prefix.

    `endpoint_host` set => a custom S3 endpoint is configured and
    `s5cmd` uses path-style addressing (`/{bucket}/{key}`), so the
    bucket lives in the path. `endpoint_host` None => no custom
    endpoint (real AWS), `s5cmd` uses virtual-hosted-style
    (`{bucket}.s3[.{region}].amazonaws.com/{key}`).
    """

    bucket: str
    endpoint_host: str | None
    endpoint_port: int | None

    @classmethod
    def from_env(cls) -> "SnapshotEgressPolicy | None":
        """Build from the proxy's env, or None if no bucket is set.

        The proxy receives the deployment configmap via `envFrom`, so
        it sees the same `SANDBOX_S3_BUCKET` and S3 endpoint the
        sidecar's `s5cmd` connects to. `AWS_ENDPOINT_URL` is the
        cluster-reachable endpoint the manager mirrors into the
        sidecar's `S3_ENDPOINT_URL`; fall back to `S3_ENDPOINT_URL`.
        """
        if not SANDBOX_S3_BUCKET:
            return None
        endpoint = os.environ.get("AWS_ENDPOINT_URL") or os.environ.get(
            "S3_ENDPOINT_URL"
        )
        host: str | None = None
        port: int | None = None
        if endpoint:
            parsed = urlparse(endpoint)
            host = parsed.hostname
            port = parsed.port
        return cls(bucket=SANDBOX_S3_BUCKET, endpoint_host=host, endpoint_port=port)

    def host_matches(self, host: str) -> bool:
        """Cheap pre-check (no DB): could this host be our S3 endpoint?

        Lets the gate skip tenant resolution for the overwhelming
        majority of flows, which aren't headed for S3 at all.
        """
        if self.endpoint_host is not None:
            return host == self.endpoint_host
        return self._is_bucket_vhost(host)

    def should_stream(
        self,
        *,
        host: str,
        port: int | None,
        path_components: tuple[str, ...],
        tenant_id: str,
    ) -> bool:
        """True iff this flow is snapshot egress to `tenant_id`'s prefix.

        `path_components` are the URL-decoded path segments without the
        leading slash (mitmproxy's `request.path_components`), so query
        params (multipart `?uploads` / `?partNumber=` / `?uploadId=`)
        are already excluded.
        """
        if self.endpoint_host is not None:
            # Path-style: /{bucket}/{tenant_id}/snapshots/...
            if host != self.endpoint_host:
                return False
            if self.endpoint_port is not None and port != self.endpoint_port:
                return False
            return path_components[:3] == (
                self.bucket,
                tenant_id,
                _SNAPSHOTS_SEGMENT,
            )

        # Virtual-hosted: {bucket}.s3[.region].amazonaws.com/{tenant_id}/snapshots/...
        if not self._is_bucket_vhost(host):
            return False
        return path_components[:2] == (tenant_id, _SNAPSHOTS_SEGMENT)

    def _is_bucket_vhost(self, host: str) -> bool:
        """Exact bucket subdomain on AWS S3 — not a broad suffix.

        Matches `{bucket}.s3.amazonaws.com`, `{bucket}.s3.{region}.
        amazonaws.com`, and the `s3-{region}` dash variant. Pins the
        bucket so `attacker-bucket.s3.amazonaws.com` does not match.
        """
        host = host.lower()
        return host.startswith(f"{self.bucket}.s3") and host.endswith(".amazonaws.com")
