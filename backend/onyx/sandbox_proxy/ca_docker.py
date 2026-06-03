"""Docker-compose implementation of the CA persistence layer.

A shared compose-named volume is the source of truth: the proxy mounts it
read-write so it can persist on cold start; every sandbox container mounts it
read-only so ``firewall-init.sh`` can install ``ca.crt`` into the trust store.

Concurrent-persist arbitration: the shipped compose deployment runs exactly one
``sandbox-proxy`` replica, so the cold-start race is not a routine concern in
docker mode. ``persist`` still rendezvouses on ``O_EXCL`` against ``ca.crt`` for
two reasons:

1. Defense against an operator running ``docker compose up --scale
   sandbox-proxy=2``. Without ``O_EXCL`` both replicas would race-overwrite each
   other's key, leaving sandbox trust stores pointing at a cert whose private
   key the proxy doesn't have.
2. Contract parity with ``K8sSecretCAStore``, which uses a 409 Conflict on
   conditional Secret create for the same rendezvous so
   ``CABootstrap.ensure_ca`` stays backend-agnostic.

The loser raises ``CAStoreConflictError`` and ``CABootstrap.ensure_ca`` falls
into the reload-the-winner branch.

Crash recovery: a crash between writing ``ca.crt`` and writing ``ca.key`` leaves
the cert without a key. The next boot's ``load()`` raises rather than silently
regenerating (which would invalidate trust stores already populated from the
orphaned cert). Operator recovery is: delete ``ca.crt``, restart proxy.
"""

import os
from pathlib import Path

from onyx.sandbox_proxy.ca import CAStore
from onyx.sandbox_proxy.ca import CAStoreConflictError
from onyx.server.features.build.configs import SANDBOX_PROXY_CA_VOLUME_PATH
from onyx.utils.logger import setup_logger

logger = setup_logger()


_CA_CERT_FILENAME = "ca.crt"
_CA_KEY_FILENAME = "ca.key"

_CA_CERT_MODE = 0o644
_CA_KEY_MODE = 0o600


class FileCAStore(CAStore):
    """File-backed CA persistence over a shared compose volume.

    Layout:
        $root/
            ca.crt   # public cert, world-readable; mounted into sandboxes
            ca.key   # private key, proxy-only

    ``persist`` is idempotent under concurrent callers via ``O_EXCL`` on the
    cert (the rendezvous file). The key is written second; if a crash interrupts
    between the two, the next boot fails loud rather than regenerating and
    invalidating trust stores.
    """

    def __init__(self, root: str | Path = SANDBOX_PROXY_CA_VOLUME_PATH) -> None:
        self._root = Path(root)
        self._cert_path = self._root / _CA_CERT_FILENAME
        self._key_path = self._root / _CA_KEY_FILENAME

    def load(self) -> tuple[bytes, bytes] | None:
        cert_exists = self._cert_path.exists()
        key_exists = self._key_path.exists()
        if not cert_exists and not key_exists:
            return None
        if cert_exists and not key_exists:
            # Half-written state from a crash mid-persist. Fail loud so the
            # operator can recover (delete ca.crt, restart) rather than silently
            # regenerating and orphaning the cert that sandboxes may have
            # already trusted.
            raise RuntimeError(
                f"Proxy CA cert exists at {self._cert_path} but key is missing at "
                f"{self._key_path}; refusing to regenerate. Recovery: delete {self._cert_path} and "
                "restart the proxy."
            )
        if not cert_exists and key_exists:
            # Symmetric anomaly: key without cert. Same fail-loud posture.
            raise RuntimeError(
                f"Proxy CA key exists at {self._key_path} but cert is missing at "
                f"{self._cert_path}; refusing to regenerate. Recovery: delete {self._key_path} and "
                "restart the proxy."
            )
        cert_pem = self._cert_path.read_bytes()
        key_pem = self._key_path.read_bytes()
        return cert_pem, key_pem

    def persist(self, cert_pem: bytes, key_pem: bytes) -> None:
        self._root.mkdir(parents=True, exist_ok=True)

        # Cert first: it's the rendezvous file. Losing the O_EXCL race here
        # means another replica won; raise so CABootstrap re-load()s the
        # winner's CA.
        try:
            fd = os.open(
                self._cert_path,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                _CA_CERT_MODE,
            )
        except FileExistsError as e:
            raise CAStoreConflictError(
                f"Proxy CA cert already present at {self._cert_path}."
            ) from e
        # Wrap the fd in a buffered writer so ``write`` loops on short writes.
        # ``os.write`` is a thin wrapper around write(2) and POSIX permits it to
        # return fewer bytes than requested; for regular files this is rare but
        # a truncated CA would propagate silently into every sandbox's trust
        # store.
        with os.fdopen(fd, "wb") as f:
            f.write(cert_pem)
        # mkdir + O_CREAT honor umask; chmod explicitly so a restrictive umask
        # doesn't leave sandboxes unable to read the cert.
        os.chmod(self._cert_path, _CA_CERT_MODE)

        # Key second. If this fails the cert is orphaned -- next load() raises
        # the half-written-state error above.
        fd = os.open(
            self._key_path,
            os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
            _CA_KEY_MODE,
        )
        with os.fdopen(fd, "wb") as f:
            f.write(key_pem)
        os.chmod(self._key_path, _CA_KEY_MODE)

        logger.info(
            "Persisted proxy CA cert=%s key=%s",
            self._cert_path,
            self._key_path,
        )
