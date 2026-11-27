"""Changes the test share as the domain administrator: files, timestamps
and NTFS access lists. smbclient has no public call for an access
list, so this uses its file transaction, as the gateway does."""

import uuid
from typing import Any

import smbclient
import smbclient.shutil
from smbclient._io import SMBFileTransaction, SMBRawIO
from smbprotocol.file_info import InfoType
from smbprotocol.open import CreateOptions, SMB2SetInfoRequest, SMB2SetInfoResponse
from smbprotocol.security_descriptor import (
    AccessAllowedAce,
    AccessDeniedAce,
    AclPacket,
    SDControl,
    SIDPacket,
    SMB2CreateSDBuffer,
)

from onyx.connectors.smb.security_descriptor import Ace, AceKind

FULL_CONTROL = 0x001F01FF
FILE_GENERIC_READ = 0x00120089
ADMINISTRATORS_SID = "S-1-5-32-544"
_DACL_SECURITY_INFORMATION = 0x4
_READ_CONTROL = 0x00020000
_WRITE_DAC = 0x00040000
_RELATED_FILE_ID = b"\xff" * 16


def allow(sid: str, mask: int = FILE_GENERIC_READ) -> Ace:
    return Ace(kind=AceKind.ALLOW, sid=sid, mask=mask)


def deny(sid: str, mask: int = FILE_GENERIC_READ) -> Ace:
    return Ace(kind=AceKind.DENY, sid=sid, mask=mask)


def _sid(sid: str) -> SIDPacket:
    packet = SIDPacket()
    packet.from_string(sid)
    return packet


class ShareAdmin:
    def __init__(
        self, *, host: str, port: int, share: str, username: str, password: str
    ) -> None:
        self._root = f"\\\\{host}\\{share}"
        self._kwargs: dict[str, Any] = {
            "username": username,
            "password": password,
            "port": port,
            "connection_cache": {},
            "auth_protocol": "ntlm",
        }

    def unc(self, path: str) -> str:
        return f"{self._root}\\{path.replace('/', '\\')}" if path else self._root

    def close(self) -> None:
        smbclient.reset_connection_cache(
            fail_on_error=False, connection_cache=self._kwargs["connection_cache"]
        )

    def make_workspace(self) -> str:
        """A new folder for one test, under the share root."""
        name = f"test-{uuid.uuid4().hex[:12]}"
        smbclient.mkdir(self.unc(name), **self._kwargs)
        return name

    def mkdir(self, path: str) -> None:
        smbclient.makedirs(self.unc(path), exist_ok=True, **self._kwargs)

    def write(self, path: str, content: str) -> None:
        """Writes a text file, with the folders above it."""
        if "/" in path:
            self.mkdir(path.rsplit("/", 1)[0])
        with smbclient.open_file(self.unc(path), mode="wb", **self._kwargs) as file:
            file.write(content.encode())

    def rename(self, old: str, new: str) -> None:
        smbclient.rename(self.unc(old), self.unc(new), **self._kwargs)

    def remove(self, path: str) -> None:
        smbclient.remove(self.unc(path), **self._kwargs)

    def rmtree(self, path: str) -> None:
        smbclient.shutil.rmtree(self.unc(path), **self._kwargs)

    def set_last_write_time(self, path: str, seconds: float) -> None:
        """The file keeps its creation time, like a file copied onto the
        share with its old last write time."""
        smbclient.utime(self.unc(path), times=(seconds, seconds), **self._kwargs)

    def set_dacl(self, path: str, aces: list[Ace]) -> None:
        """Replaces the access list. It inherits nothing. Administrators keep
        full control, so the test can clean up."""
        acl = AclPacket()
        acl["aces"] = [
            self._ace(ace) for ace in [*aces, allow(ADMINISTRATORS_SID, FULL_CONTROL)]
        ]
        descriptor = SMB2CreateSDBuffer()
        descriptor["control"].set_flag(SDControl.SELF_RELATIVE)
        descriptor["control"].set_flag(SDControl.DACL_PROTECTED)
        descriptor.set_dacl(acl)

        request = SMB2SetInfoRequest()
        request["info_type"] = InfoType.SMB2_0_INFO_SECURITY
        request["additional_information"] = _DACL_SECURITY_INFORMATION
        request["file_id"] = _RELATED_FILE_ID
        request["buffer"] = descriptor

        raw = SMBRawIO(
            self.unc(path),
            mode="r",
            share_access="rwd",
            desired_access=_READ_CONTROL | _WRITE_DAC,
            file_attributes=0,
            create_options=CreateOptions.FILE_OPEN_REPARSE_POINT,
            **self._kwargs,
        )

        def receive(sent: Any) -> None:
            response = raw.fd.connection.receive(sent)
            SMB2SetInfoResponse().unpack(response["data"].get_value())

        transaction = SMBFileTransaction(raw)
        transaction += (request, receive)
        transaction.commit()

    @staticmethod
    def _ace(ace: Ace) -> AccessAllowedAce | AccessDeniedAce:
        packet = AccessAllowedAce() if ace.kind is AceKind.ALLOW else AccessDeniedAce()
        packet["mask"] = ace.mask
        packet["sid"] = _sid(ace.sid)
        return packet
