"""The Kerberos settings of this process, for the Windows file share
connector.

The MIT Kerberos library reads its settings from files, not from the caller.
Onyx keeps one file for the process, names it in ``KRB5_CONFIG`` ahead of the
system's file, and writes each realm a credential names into it. The library
reads the files again for each new context, so a new realm needs no restart.

The file is shared by every credential in the process, so the first
credential to name a realm or a server decides its entry. A later credential
with a different KDC host or a different realm for the server is refused: it
could otherwise send another credential's sign-in to a KDC of its choice.

The library never looks for a KDC or a realm through DNS, because the network
policy cannot check a host that DNS names. A realm without a KDC host gets no
entry, and then works only if the system's own file names its KDC.
"""

import os
import re
import tempfile
import threading
from pathlib import Path

from onyx.utils.logger import setup_logger

logger = setup_logger()

_ENV_VAR = "KRB5_CONFIG"
_SYSTEM_CONFIG = "/etc/krb5.conf"
_FILE_NAME = "krb5.conf"
# The values go into a settings file, so nothing but these characters may.
_REALM_PATTERN = re.compile(r"[A-Z0-9][A-Z0-9.-]{0,253}")
_HOST_PATTERN = re.compile(r"[A-Za-z0-9]([A-Za-z0-9.-]{0,251}[A-Za-z0-9])?")

_lock = threading.Lock()
# Realm -> the KDC host its first credential named.
_kdc_hosts: dict[str, str] = {}
# Realm -> the addresses of that host that passed the network policy.
_kdcs: dict[str, set[str]] = {}
# Host -> the realm that issues tickets for it.
_host_realms: dict[str, str] = {}
_config_path: Path | None = None


def is_valid_realm(realm: str) -> bool:
    return bool(_REALM_PATTERN.fullmatch(realm))


def is_valid_host(host: str) -> bool:
    return bool(_HOST_PATTERN.fullmatch(host))


def _render() -> str:
    lines: list[str] = [
        "[libdefaults]",
        # The name an admin entered is the name in the service ticket.
        "    dns_canonicalize_hostname = false",
        "    rdns = false",
        # A host that DNS names would skip the network policy.
        "    dns_lookup_kdc = false",
        "    dns_lookup_realm = false",
        # UDP answers that are too large fail behind some firewalls.
        "    udp_preference_limit = 1",
        "",
        "[realms]",
    ]
    for realm in sorted(_kdcs):
        lines.append(f"    {realm} = {{")
        lines.extend(f"        kdc = {kdc}" for kdc in sorted(_kdcs[realm]))
        lines.append("    }")
    lines.extend(["", "[domain_realm]"])
    lines.extend(
        f"    {host} = {realm}" for host, realm in sorted(_host_realms.items())
    )
    return "\n".join(lines) + "\n"


class KerberosConflictError(ValueError):
    """Another credential in this process already set a different value."""


def register_realm(
    realm: str,
    kdc_host: str | None,
    kdc_addresses: list[str],
    service_hosts: list[str],
) -> None:
    """Makes the realm usable in this process. ``kdc_addresses`` are the
    addresses of ``kdc_host`` that passed the network policy: the file holds
    them, not the name, so the library connects to what was checked.
    ``service_hosts`` are the servers whose tickets the realm issues, which
    matters when a server's DNS domain differs from the realm's name."""
    global _config_path  # noqa: PLW0603 - one settings file per process
    if not is_valid_realm(realm):
        raise ValueError("The Kerberos realm holds a character that is not allowed.")
    hosts: list[str] = [host.lower() for host in service_hosts if host]
    for host in [*hosts, *kdc_addresses, *([kdc_host] if kdc_host else [])]:
        if not is_valid_host(host.replace(":", ".")):
            raise ValueError(
                "A Kerberos host name holds a character that is not allowed."
            )
    with _lock:
        known_kdc: str | None = _kdc_hosts.get(realm)
        if kdc_host and known_kdc and known_kdc.lower() != kdc_host.lower():
            raise KerberosConflictError(
                f"Another credential uses the KDC '{known_kdc}' for the realm "
                f"{realm}. Use the same KDC host, or restart Onyx to change it."
            )
        for host in hosts:
            known_realm: str | None = _host_realms.get(host)
            if known_realm is not None and known_realm != realm:
                raise KerberosConflictError(
                    f"Another credential uses the realm {known_realm} for the "
                    f"server '{host}'. Use the same realm, or restart Onyx to "
                    "change it."
                )
        changed: bool = _config_path is None
        if kdc_host:
            _kdc_hosts.setdefault(realm, kdc_host)
            if not set(kdc_addresses) <= _kdcs.setdefault(realm, set()):
                _kdcs[realm].update(kdc_addresses)
                changed = True
        for host in hosts:
            if host not in _host_realms:
                _host_realms[host] = realm
                changed = True
        if not changed:
            return
        if _config_path is None:
            _config_path = Path(tempfile.mkdtemp(prefix="onyx-krb5-")) / _FILE_NAME
        # A reader never sees half a file.
        temporary: Path = _config_path.with_suffix(".tmp")
        temporary.write_text(_render())
        temporary.replace(_config_path)
        own: str = str(_config_path)
        current: str = os.environ.get(_ENV_VAR, "")
        if own not in current.split(":"):
            # The first file wins where two files set one value.
            os.environ[_ENV_VAR] = f"{own}:{current or _SYSTEM_CONFIG}"
            logger.info("Kerberos settings for this process are in %s", own)
