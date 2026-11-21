import os
import sys
from pathlib import Path

import pytest

from shared_configs import ca_bundle

_CA_VARS = ("SSL_CERT_FILE", "REQUESTS_CA_BUNDLE")


@pytest.fixture
def homebrew_bundle(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    bundle = tmp_path / "cert.pem"
    bundle.write_text("")
    monkeypatch.setattr(ca_bundle, "_HOMEBREW_CA_BUNDLES", (str(bundle),))
    monkeypatch.setattr(sys, "platform", "darwin")
    # An isolated copy, so what the helper writes never outlives the test.
    env = {k: v for k, v in os.environ.items() if k not in _CA_VARS}
    monkeypatch.setattr(os, "environ", env)
    return bundle


def test_sets_both_vars_on_macos(homebrew_bundle: Path) -> None:
    ca_bundle.prefer_homebrew_ca_bundle_on_macos()
    assert os.environ["SSL_CERT_FILE"] == str(homebrew_bundle)
    assert os.environ["REQUESTS_CA_BUNDLE"] == str(homebrew_bundle)


@pytest.mark.usefixtures("homebrew_bundle")
def test_noop_off_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "platform", "linux")
    ca_bundle.prefer_homebrew_ca_bundle_on_macos()
    assert "SSL_CERT_FILE" not in os.environ


@pytest.mark.usefixtures("homebrew_bundle")
def test_explicit_ssl_cert_file_wins(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("SSL_CERT_FILE", "/custom/bundle.pem")
    ca_bundle.prefer_homebrew_ca_bundle_on_macos()
    assert os.environ["SSL_CERT_FILE"] == "/custom/bundle.pem"
    assert "REQUESTS_CA_BUNDLE" not in os.environ


def test_noop_without_homebrew_bundle(homebrew_bundle: Path) -> None:
    homebrew_bundle.unlink()
    ca_bundle.prefer_homebrew_ca_bundle_on_macos()
    assert "SSL_CERT_FILE" not in os.environ
