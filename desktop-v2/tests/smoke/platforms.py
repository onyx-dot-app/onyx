"""Per-OS hooks for the runtime smoke test.

Each hook is something WebDriver cannot do: press a global shortcut, write the
managed policy, read the OS credential store, see native windows, and take a
screenshot of the whole screen. Only Linux is implemented; see
`desktop-v2/tests/README.md` for the Windows and macOS plans.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Protocol

SERVICE = "app.onyx.desktop.v2"
LINUX_POLICY = Path("/etc/onyx-desktop/policy.json")


class Platform(Protocol):
    default_binary: str
    launcher_shortcut: str

    def config_file(self, home: Path) -> Path: ...

    def write_policy(self, policy: dict[str, str | bool] | None) -> None: ...

    def stored_token(self, server: str) -> bool: ...

    def press_launcher_shortcut(self) -> None: ...

    def window_visible(self, title: str) -> bool: ...

    def screenshot(self, path: Path) -> None: ...


class Linux:
    """X11 (Xvfb) session with a D-Bus session bus and an unlocked GNOME Keyring."""

    default_binary = "/usr/bin/onyx-desktop-v2"
    launcher_shortcut = "ctrl+alt+space"

    def __init__(self) -> None:
        for tool in ("xdotool", "import", "secret-tool"):
            if shutil.which(tool) is None:
                raise SystemExit(f"{tool} is missing (see desktop-v2/tests/README.md)")
        if not os.environ.get("DISPLAY") or not os.environ.get(
            "DBUS_SESSION_BUS_ADDRESS"
        ):
            raise SystemExit("run under run-linux.sh (needs DISPLAY and a D-Bus bus)")
        self._policy_backup: bytes | None = (
            LINUX_POLICY.read_bytes() if LINUX_POLICY.exists() else None
        )

    def config_file(self, home: Path) -> Path:
        return home / ".config" / SERVICE / "config.json"

    def write_policy(self, policy: dict[str, str | bool] | None) -> None:
        """Writes the machine policy (needs passwordless sudo); None restores the original."""
        if policy is None:
            if self._policy_backup is None:
                subprocess.run(["sudo", "rm", "-f", str(LINUX_POLICY)], check=True)
                return
            data = self._policy_backup
        else:
            data = json.dumps(policy).encode()
        subprocess.run(["sudo", "mkdir", "-p", str(LINUX_POLICY.parent)], check=True)
        subprocess.run(
            ["sudo", "tee", str(LINUX_POLICY)],
            input=data,
            stdout=subprocess.DEVNULL,
            check=True,
        )
        subprocess.run(["sudo", "chmod", "644", str(LINUX_POLICY)], check=True)

    def stored_token(self, server: str) -> bool:
        # The keyring crate stores `service` and `username` (= the server URL).
        found = subprocess.run(
            ["secret-tool", "lookup", "service", SERVICE, "username", server],
            capture_output=True,
            text=True,
            check=False,
        )
        return found.returncode == 0 and bool(found.stdout.strip())

    def press_launcher_shortcut(self) -> None:
        # XTEST input goes through the X server, so the app's XGrabKey sees it.
        subprocess.run(["xdotool", "key", self.launcher_shortcut], check=True)

    def window_visible(self, title: str) -> bool:
        found = subprocess.run(
            ["xdotool", "search", "--onlyvisible", "--name", f"^{title}$"],
            capture_output=True,
            text=True,
            check=False,
        )
        return bool(found.stdout.strip())

    def screenshot(self, path: Path) -> None:
        subprocess.run(["import", "-window", "root", str(path)], check=True)


def current() -> Platform:
    if sys.platform.startswith("linux"):
        return Linux()
    raise SystemExit(
        f"{sys.platform} is not implemented yet; see desktop-v2/tests/README.md"
    )
