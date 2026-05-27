"""Tenant-scoped allowlist for sidecar snapshot egress.

The gate's 1 MiB body cap is right for the agent's external-app calls but
also catches the sidecar's snapshot upload (`tar -czf - | s5cmd pipe
s3://...`), whose multipart parts exceed it; buffering them is a DoS
surface. This policy decides whether a flow is a snapshot upload to the
configured bucket under the *resolving tenant's* own prefix, in which case
the gate streams the body unbuffered (`flow.request.stream = True`).

Scope is deliberately narrow to prevent a prompt-injected agent from
streaming uncapped to another tenant's prefix or an arbitrary host:

* exact endpoint host or the bucket's virtual-hosted AWS subdomain — never
  a broad `*.amazonaws.com` suffix.
* key under `{tenant_id}/snapshots/...`, where `tenant_id` is resolved from
  the source pod IP (matters most on shared path-style MinIO).

Key layout mirrors `sandbox_daemon/snapshot.py`:
`{tenant_id}/snapshots/{session_id}/{snapshot_id}.tar.gz` in `SANDBOX_S3_BUCKET`.
"""

import os
from dataclasses import dataclass
from urllib.parse import urlparse

from onyx.server.features.build.configs import SANDBOX_S3_BUCKET

_SNAPSHOTS_SEGMENT = "snapshots"


@dataclass(frozen=True)
class SnapshotEgressPolicy:
    """`endpoint_host` set => custom endpoint, `s5cmd` uses path-style
    (`/{bucket}/{key}`). `endpoint_host` None => real AWS, virtual-hosted
    (`{bucket}.s3[.{region}].amazonaws.com/{key}`)."""

    bucket: str
    endpoint_host: str | None
    endpoint_port: int | None

    @classmethod
    def from_env(cls) -> "SnapshotEgressPolicy | None":
        """Build from the proxy's env (shared with the sidecar via `envFrom`),
        or None if no bucket is set. `AWS_ENDPOINT_URL` is the cluster-reachable
        endpoint; fall back to `S3_ENDPOINT_URL`."""
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
        """Cheap no-DB pre-check so the gate skips tenant resolution for non-S3 flows."""
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

        `path_components` is mitmproxy's URL-decoded path segments, so the
        multipart query params (`?uploads` / `?partNumber=` / `?uploadId=`)
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
        """Exact bucket subdomain (all region variants), not a broad suffix, so
        `attacker-bucket.s3.amazonaws.com` does not match."""
        host = host.lower()
        return host.startswith(f"{self.bucket}.s3") and host.endswith(".amazonaws.com")
