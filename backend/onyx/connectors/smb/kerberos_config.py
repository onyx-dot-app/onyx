"""The Kerberos settings of this process, for the Windows file share
connector.

The MIT Kerberos library reads its settings from files, not from the caller.
Onyx keeps one file for the process, names it in ``KRB5_CONFIG`` ahead of the
system's file, and writes each realm a credential names into it. The library
reads the files again for each new context, so a new realm needs no restart.

A realm without a KDC host gets no entry: the library then finds the KDC
through DNS SRV records.
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
# Realm -> its KDC hosts.
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


def register_realm(realm: str, kdc: str | None, service_hosts: list[str]) -> None:
    """Makes the realm usable in this process. ``service_hosts`` are the
    servers whose tickets the realm issues, which matters when a server's DNS
    domain differs from the realm's name."""
    global _config_path  # noqa: PLW0603 - one settings file per process
    if not is_valid_realm(realm):
        raise ValueError("The Kerberos realm holds a character that is not allowed.")
    hosts: list[str] = [host.lower() for host in service_hosts if host]
    for host in [*hosts, *([kdc] if kdc else [])]:
        if not is_valid_host(host):
            raise ValueError(
                "A Kerberos host name holds a character that is not allowed."
            )
    with _lock:
        changed: bool = _config_path is None
        if kdc and kdc not in _kdcs.setdefault(realm, set()):
            _kdcs[realm].add(kdc)
            changed = True
        for host in hosts:
            if _host_realms.get(host) != realm:
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
