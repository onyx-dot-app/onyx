"""The guest daemon's TLS channel of a container sandbox.

Each container gets its own key and a self-signed certificate at create.
The client trusts only that certificate (it is the root of the channel), so
no other server can answer for the sandbox, and the bearer key never leaves
TLS.
"""

import datetime
import hashlib
import secrets
import threading
from collections import OrderedDict

import grpc
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID
from pydantic import SecretStr

from onyx.microvm.agent_client import MAX_MESSAGE_BYTES
from onyx.server.features.build.sandbox.container.models import DaemonCredentials

# The name in every daemon certificate. The channel checks it instead of the
# dialed address, which changes (pod IP, published port).
DAEMON_TLS_SERVER_NAME = "sandboxd.onyx.internal"
# Longer than any container lives: the idle stop deletes it much sooner.
_CERT_DAYS = 365
# Channels kept; the least recently used is dropped first (containers come
# and go). A dropped channel closes once no call uses it.
_MAX_CHANNELS = 256


def new_daemon_credentials() -> DaemonCredentials:
    private_key = ec.generate_private_key(ec.SECP256R1())
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, DAEMON_TLS_SERVER_NAME)])
    now = datetime.datetime.now(datetime.UTC)
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(private_key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=5))
        .not_valid_after(now + datetime.timedelta(days=_CERT_DAYS))
        .add_extension(
            x509.SubjectAlternativeName([x509.DNSName(DAEMON_TLS_SERVER_NAME)]),
            critical=False,
        )
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .sign(private_key, hashes.SHA256())
    )
    return DaemonCredentials(
        # Printable ASCII without spaces: calls send it as metadata.
        key=SecretStr(secrets.token_hex(32)),
        cert_pem=cert.public_bytes(serialization.Encoding.PEM).decode(),
        private_key_pem=SecretStr(
            private_key.private_bytes(
                serialization.Encoding.PEM,
                serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption(),
            ).decode()
        ),
    )


class DaemonChannelPool:
    """One TLS channel per (address, pinned certificate), shared between
    calls. A new certificate at the same address gets a new channel."""

    def __init__(self, max_channels: int = _MAX_CHANNELS) -> None:
        self._lock = threading.Lock()
        self._max = max_channels
        self._channels: OrderedDict[tuple[str, str], grpc.Channel] = OrderedDict()

    def channel(self, address: str, cert_pem: str) -> grpc.Channel:
        key = (address, hashlib.sha256(cert_pem.encode()).hexdigest())
        with self._lock:
            channel = self._channels.get(key)
            if channel is not None:
                self._channels.move_to_end(key)
            else:
                channel = grpc.secure_channel(
                    address,
                    grpc.ssl_channel_credentials(root_certificates=cert_pem.encode()),
                    [
                        ("grpc.ssl_target_name_override", DAEMON_TLS_SERVER_NAME),
                        ("grpc.max_receive_message_length", MAX_MESSAGE_BYTES),
                        ("grpc.max_send_message_length", MAX_MESSAGE_BYTES),
                    ],
                )
                self._channels[key] = channel
                while len(self._channels) > self._max:
                    self._channels.popitem(last=False)
            return channel
