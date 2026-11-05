"""Host agent client against an in-process gRPC server: typed results, typed
errors from google.rpc.ErrorInfo, and the mTLS channel."""

import datetime
import ipaddress
from collections.abc import Generator
from pathlib import Path

import grpc
import pytest
from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from onyx.microvm.agent_client import (
    HostAgentClient,
    HostAgentError,
    HostAgentErrorReason,
    MtlsHostAgentClientFactory,
    VmState,
)
from tests.external_dependency_unit.microvm.fake_agent import (
    FakeHostAgent,
    InsecureClientFactory,
    RunningFakeAgent,
)

SANDBOX_ID = "6b9f3f0e-6a39-4f3c-9b51-6a3b5f0b9d11"


@pytest.fixture
def running() -> Generator[RunningFakeAgent, None, None]:
    agent = RunningFakeAgent(FakeHostAgent())
    yield agent
    agent.stop()


def test_calls_return_typed_results(running: RunningFakeAgent) -> None:
    factory = InsecureClientFactory()
    client = factory.client(running.address)

    info = client.node_info()
    assert info.mem_available_mib == 16_384
    assert info.template("tpl-1") is not None

    created = client.create(
        sandbox_id=SANDBOX_ID,
        attempt=1,
        template="tpl-1",
        vcpus=2,
        mem_mib=2048,
        scratch_gib=4,
        tenant_id="public",
    )
    assert created.created
    assert created.vm.state is VmState.RUNNING

    vms = client.list_vms()
    assert [vm.generation for vm in vms] == [created.vm.generation]
    assert (
        client.close_connections(
            sandbox_id=SANDBOX_ID, attempt=1, generation=created.vm.generation
        )
        == 3
    )
    assert not client.stop(
        sandbox_id=SANDBOX_ID, attempt=1, generation=created.vm.generation
    )
    factory.close()


def test_error_info_reason_is_typed(running: RunningFakeAgent) -> None:
    running.agent.refuse_create = HostAgentErrorReason.CAPACITY_MEMORY
    factory = InsecureClientFactory()
    with pytest.raises(HostAgentError) as exc:
        factory.client(running.address).create(
            sandbox_id=SANDBOX_ID,
            attempt=1,
            template="tpl-1",
            vcpus=2,
            mem_mib=2048,
            scratch_gib=4,
            tenant_id="public",
        )
    assert exc.value.reason is HostAgentErrorReason.CAPACITY_MEMORY
    assert exc.value.code is grpc.StatusCode.RESOURCE_EXHAUSTED
    assert exc.value.reached_agent

    with pytest.raises(HostAgentError) as exc:
        factory.client(running.address).stop(
            sandbox_id=SANDBOX_ID, attempt=1, generation=1
        )
    assert exc.value.reason is HostAgentErrorReason.SANDBOX_NOT_FOUND
    factory.close()


def test_unreachable_agent_has_no_reason() -> None:
    gone = RunningFakeAgent(FakeHostAgent())
    gone.stop()
    with HostAgentClient(grpc.insecure_channel(gone.address)) as client:
        with pytest.raises(HostAgentError) as exc:
            client.list_vms()
    assert exc.value.reason is None
    assert not exc.value.reached_agent


def _cert(
    subject: str,
    key: ec.EllipticCurvePrivateKey,
    issuer: tuple[x509.Name, ec.EllipticCurvePrivateKey] | None,
    *,
    ca: bool = False,
    dns_name: str | None = None,
) -> x509.Certificate:
    now = datetime.datetime.now(datetime.timezone.utc)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject)])
    issuer_name, issuer_key = issuer if issuer is not None else (name, key)
    builder = (
        x509.CertificateBuilder()
        .subject_name(name)
        .issuer_name(issuer_name)
        .public_key(key.public_key())
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - datetime.timedelta(minutes=1))
        .not_valid_after(now + datetime.timedelta(hours=1))
        .add_extension(x509.BasicConstraints(ca=ca, path_length=None), critical=True)
    )
    if dns_name is not None:
        builder = builder.add_extension(
            x509.SubjectAlternativeName(
                [
                    x509.DNSName(dns_name),
                    x509.IPAddress(ipaddress.ip_address("127.0.0.2")),
                ]
            ),
            critical=False,
        )
    return builder.sign(issuer_key, hashes.SHA256())


def _pem(cert: x509.Certificate) -> bytes:
    return cert.public_bytes(serialization.Encoding.PEM)


def _key_pem(key: ec.EllipticCurvePrivateKey) -> bytes:
    return key.private_bytes(
        serialization.Encoding.PEM,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


def test_mtls_channel(tmp_path: Path) -> None:
    ca_key = ec.generate_private_key(ec.SECP256R1())
    ca = _cert("test-ca", ca_key, None, ca=True)
    issuer = (ca.subject, ca_key)
    server_key = ec.generate_private_key(ec.SECP256R1())
    server = _cert("agent", server_key, issuer, dns_name="host-agent.test")
    client_key = ec.generate_private_key(ec.SECP256R1())
    client = _cert("api-server", client_key, issuer)
    stranger_ca_key = ec.generate_private_key(ec.SECP256R1())
    stranger_ca = _cert("other-ca", stranger_ca_key, None, ca=True)
    stranger_key = ec.generate_private_key(ec.SECP256R1())
    stranger = _cert("intruder", stranger_key, (stranger_ca.subject, stranger_ca_key))

    for name, data in {
        "ca.crt": _pem(ca),
        "client.crt": _pem(client),
        "client.key": _key_pem(client_key),
        "stranger.crt": _pem(stranger),
        "stranger.key": _key_pem(stranger_key),
    }.items():
        (tmp_path / name).write_bytes(data)

    credentials = grpc.ssl_server_credentials(
        [(_key_pem(server_key), _pem(server))],
        root_certificates=_pem(ca),
        require_client_auth=True,
    )
    running = RunningFakeAgent(FakeHostAgent(), server_credentials=credentials)
    try:
        good = MtlsHostAgentClientFactory(
            cert_path=str(tmp_path / "client.crt"),
            key_path=str(tmp_path / "client.key"),
            ca_path=str(tmp_path / "ca.crt"),
            server_name="host-agent.test",
        )
        assert good.client(running.address).node_info().agent_version == "test"

        bad = MtlsHostAgentClientFactory(
            cert_path=str(tmp_path / "stranger.crt"),
            key_path=str(tmp_path / "stranger.key"),
            ca_path=str(tmp_path / "ca.crt"),
            server_name="host-agent.test",
        )
        with pytest.raises(HostAgentError) as exc:
            bad.client(running.address).node_info()
        assert exc.value.reason is None
    finally:
        running.stop()
