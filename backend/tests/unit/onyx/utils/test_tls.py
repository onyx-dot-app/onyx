import datetime as dt
import ssl
from pathlib import Path

import certifi
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.x509.oid import NameOID

from onyx.utils.tls import build_ssl_context

_CA_BUNDLE = certifi.where()


def _self_signed(out_path: Path) -> tuple[str, str]:
    out_path.mkdir(parents=True, exist_ok=True)
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, "onyx-test")])
    cert = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc))
        .not_valid_after(dt.datetime(2040, 1, 1, tzinfo=dt.timezone.utc))
        .sign(key, hashes.SHA256())
    )
    cert_path = out_path / "c.crt"
    key_path = out_path / "c.key"
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    key_path.write_bytes(
        key.private_bytes(
            serialization.Encoding.PEM,
            serialization.PrivateFormat.TraditionalOpenSSL,
            serialization.NoEncryption(),
        )
    )
    return str(cert_path), str(key_path)


def test_verify_mode_and_hostname_applied() -> None:
    ctx = build_ssl_context(
        verify_mode=ssl.CERT_REQUIRED, check_hostname=True, ca_certs=_CA_BUNDLE
    )
    assert ctx.check_hostname is True
    assert ctx.verify_mode == ssl.CERT_REQUIRED


def test_cert_none_requires_hostname_off() -> None:
    # check_hostname must be cleared before CERT_NONE — the helper handles the
    # ordering so this must not raise.
    ctx = build_ssl_context(verify_mode=ssl.CERT_NONE, check_hostname=False)
    assert ctx.verify_mode == ssl.CERT_NONE


def test_loads_client_cert(tmp_path: Path) -> None:
    cert, key = _self_signed(tmp_path)
    ctx = build_ssl_context(
        verify_mode=ssl.CERT_NONE,
        check_hostname=False,
        certfile=cert,
        keyfile=key,
    )
    assert isinstance(ctx, ssl.SSLContext)


def test_mismatched_client_key_raises(tmp_path: Path) -> None:
    cert, _ = _self_signed(tmp_path)
    _, other_key = _self_signed(tmp_path / "other")
    with pytest.raises(ssl.SSLError):
        build_ssl_context(
            verify_mode=ssl.CERT_NONE,
            check_hostname=False,
            certfile=cert,
            keyfile=other_key,
        )
