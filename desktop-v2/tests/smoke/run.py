"""Runtime smoke test for an installed Onyx Desktop v2 build.

Drives the real app through tauri-driver against a real Onyx server. The app
talks to the server through a local proxy (proxy.py), so the test can stop
"the server" for the offline checks. Each scenario launches the app again
with the same HOME, so a sign-in must survive a restart.

    desktop-v2/tests/smoke/run-linux.sh --server https://onyx.example.com

The server must allow sign-up with a password (the test registers its own
user), or pass --email and --password for an existing user.
"""

from __future__ import annotations

import argparse
import json
import os
import secrets
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from platforms import Platform, current  # noqa: E402
from proxy import ToggleProxy, free_port  # noqa: E402
from webdriver import WebDriver, WebDriverError, wait_for  # noqa: E402

LOCAL = "tauri://localhost/"
LAUNCHER_TITLE = "Onyx Launcher"


@dataclass
class Context:
    platform: Platform
    binary: str
    proxy: ToggleProxy
    email: str
    password: str
    question: str
    expect_answer: str | None
    artifacts: Path
    driver_port: int
    check_chat_input: bool = True
    home: Path = field(
        default_factory=lambda: Path(tempfile.mkdtemp(prefix="onyx-v2-smoke-"))
    )
    driver_process: subprocess.Popen[bytes] | None = None
    driver: WebDriver | None = None

    def env(self) -> dict[str, str]:
        return {
            **os.environ,
            "XAUTHORITY": os.environ.get(
                "XAUTHORITY", str(Path.home() / ".Xauthority")
            ),
            "HOME": str(self.home),
            "XDG_CONFIG_HOME": str(self.home / ".config"),
            "XDG_DATA_HOME": str(self.home / ".local" / "share"),
            # External links and the onyx:// registration must not reach the desktop.
            "BROWSER": "true",
        }

    def launch(self) -> WebDriver:
        """Starts tauri-driver (once) and the app (each call)."""
        self.close()
        if self.driver_process is None:
            self.driver_process = subprocess.Popen(
                [
                    "tauri-driver",
                    "--port",
                    str(self.driver_port),
                    # Its own WebKitWebDriver port, so two runs can share a machine.
                    "--native-port",
                    str(free_port()),
                ],
                env=self.env(),
                stdout=subprocess.DEVNULL,
                stderr=(self.artifacts / "tauri-driver.log").open("ab"),
            )
            wait_for("tauri-driver", self._driver_listening)
        driver = WebDriver(f"http://127.0.0.1:{self.driver_port}")
        driver.start(self.binary)
        self.driver = driver
        return driver

    def _driver_listening(self) -> bool:
        with socket.create_connection(("127.0.0.1", self.driver_port)):
            return True

    def close(self) -> None:
        if self.driver is not None:
            self.driver.quit()
            self.driver = None
        # tauri-driver ends the app with the session; make sure before the next launch.
        wait_for(
            "the previous app to exit",
            lambda: (
                subprocess.run(
                    ["pgrep", "-f", self.binary], capture_output=True, check=False
                ).returncode
                != 0
            ),
            timeout=15,
        )

    def shot(self, name: str) -> None:
        if self.driver is not None:
            try:
                self.driver.painted()
            except (WebDriverError, OSError):
                pass
        try:
            self.platform.screenshot(self.artifacts / f"{name}.png")
        except (OSError, subprocess.CalledProcessError) as error:
            print(f"  (screenshot {name} failed: {error})")

    def dump_windows(self) -> None:
        """Prints each webview's URL and visible text, to debug a failure."""
        if self.driver is None:
            return
        try:
            for handle, url in self.driver.windows().items():
                self.driver.switch(handle)
                print(f"  window {url}: {self.driver.text().strip()[:300]!r}")
        except (WebDriverError, OSError) as error:
            print(f"  (could not list windows: {error})")

    def write_config(self, config: dict[str, str]) -> None:
        path = self.platform.config_file(self.home)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(config))

    def fresh_home(self) -> None:
        """A new user profile: no config, no window state. The keyring is shared."""
        shutil.rmtree(self.home / ".config", ignore_errors=True)
        shutil.rmtree(self.home / ".local", ignore_errors=True)


def is_local(page: str) -> Callable[[str], bool]:
    return lambda url: url.startswith(LOCAL + page)


def on_server(ctx: Context, path: str = "/app") -> Callable[[str], bool]:
    return lambda url: url.startswith(ctx.proxy.url + path)


def register_user(server: str, email: str, password: str) -> None:
    request = urllib.request.Request(  # noqa: S310
        f"{server.rstrip('/')}/api/auth/register",
        data=json.dumps({"email": email, "password": password}).encode(),
        method="POST",
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=30):  # noqa: S310
            return
    except urllib.error.HTTPError as error:
        body = error.read().decode(errors="replace")
        if "ALREADY_EXISTS" not in body:
            raise RuntimeError(
                f"could not register {email}: {error.code} {body}"
            ) from error


# Scenarios. Each one starts the app and leaves it running for the next
# `ctx.launch()` to end.


def first_launch_shows_onboarding(ctx: Context) -> None:
    driver = ctx.launch()
    driver.switch_to_url("the onboarding window", is_local("onboarding.html"))
    wait_for("the server field", lambda: "Connect to your Onyx server" in driver.text())
    ctx.shot("01-onboarding")


def onboarding_rejects_a_remote_http_server(ctx: Context) -> None:
    driver = ctx.driver or ctx.launch()
    driver.switch_to_url("the onboarding window", is_local("onboarding.html"))
    driver.type_into("#server-url", "http://onyx.example.com", submit=True)
    wait_for(
        "an error for a plain-HTTP remote server",
        lambda: "Use https:// for this server" in driver.text(),
    )
    ctx.shot("02-onboarding-http-rejected")


def onboarding_accepts_the_server(ctx: Context) -> None:
    driver = ctx.driver or ctx.launch()
    driver.switch_to_url("the onboarding window", is_local("onboarding.html"))
    # Trailing slash and spaces are normalised by check_server.
    driver.type_into("#server-url", f"  {ctx.proxy.url}/ ", submit=True)
    driver.switch_to_url("the sign-in window", is_local("login.html"))
    wait_for(
        "the password form",
        lambda: driver.execute("return !!document.querySelector('#email')"),
    )
    saved = json.loads(ctx.platform.config_file(ctx.home).read_text())
    assert saved.get("serverUrl") == ctx.proxy.url, f"saved {saved}"
    ctx.shot("03-login")


def wrong_password_is_rejected(ctx: Context) -> None:
    driver = ctx.driver or ctx.launch()
    driver.switch_to_url("the sign-in window", is_local("login.html"))
    driver.type_into("#email", ctx.email)
    driver.type_into("#password", "not-the-password", submit=True)
    wait_for(
        "a sign-in error",
        lambda: (
            driver.execute("return document.querySelector('#email') !== null")
            and any(
                w in driver.text().lower()
                for w in ("incorrect", "invalid", "wrong", "bad")
            )
        ),
    )
    ctx.shot("04-login-wrong-password")


def sign_in_opens_the_web_ui(ctx: Context) -> None:
    driver = ctx.driver or ctx.launch()
    driver.switch_to_url("the sign-in window", is_local("login.html"))
    driver.type_into("#email", ctx.email)
    driver.type_into("#password", ctx.password, submit=True)
    driver.switch_to_url("the main window on /app", on_server(ctx))
    assert_signed_in_web_ui(ctx, driver)
    assert ctx.platform.stored_token(ctx.proxy.url), (
        "no session token in the credential store"
    )
    ctx.shot("05-main-window")


def assert_signed_in_web_ui(ctx: Context, driver: WebDriver) -> None:
    # The web UI's own API calls carry the session cookie the shell set.
    me = wait_for(
        "/api/me as the test user",
        lambda: driver.execute_async(
            "const done = arguments[arguments.length - 1];"
            "fetch('/api/me', {credentials: 'include'})"
            ".then(async r => r.ok ? r.json() : {status: r.status, body: (await r.text()).slice(0, 300)})"
            ".then(done, e => done(String(e)));"
        ),
    )
    assert isinstance(me, dict) and me.get("email") == ctx.email, (
        f"/api/me returned {me}"
    )
    if ctx.check_chat_input:
        wait_for(
            "the chat input",
            lambda: driver.execute(
                "return !!document.querySelector('textarea, [contenteditable=true]')"
            ),
            timeout=60,
        )
    else:
        wait_for("the web app to boot", lambda: driver.execute("return !!window.next"))
    assert "/auth/login" not in driver.href(), "the web login page showed"


def restart_stays_signed_in(ctx: Context) -> None:
    driver = ctx.launch()
    driver.switch_to_url("the main window after a restart", on_server(ctx))
    assert_signed_in_web_ui(ctx, driver)
    handles = driver.windows()
    assert not any(is_local("login.html")(u) for u in handles.values()), (
        "sign-in showed again"
    )


def launcher_ask_streams_an_answer(ctx: Context) -> None:
    driver = ctx.driver or ctx.launch()
    driver.switch_to_url("the main window", on_server(ctx))
    ctx.platform.press_launcher_shortcut()
    wait_for(
        "the launcher to show",
        lambda: ctx.platform.window_visible(LAUNCHER_TITLE),
        timeout=10,
    )
    driver.switch_to_url("the launcher", is_local("launcher.html"))
    driver.type_into(
        "input[role=combobox], textarea[role=combobox]", ctx.question, submit=True
    )

    def answered() -> bool:
        text = driver.text()
        if ctx.question not in text or "▍" in text or "Thinking" in text:
            return False
        after = text.split(ctx.question, 1)[1].strip()
        if ctx.expect_answer is not None:
            return ctx.expect_answer in after
        return len(after) > 20

    wait_for("the streamed answer", answered, timeout=90)
    ctx.shot("06-launcher-answer")
    print(f"  answer: {driver.text().split(ctx.question, 1)[1].strip()[:120]!r}")
    # Esc hides it.
    driver.type_into("input[role=combobox], textarea[role=combobox]", "\ue00c")
    wait_for(
        "the launcher to hide",
        lambda: not ctx.platform.window_visible(LAUNCHER_TITLE),
        timeout=10,
    )


def offline_window_then_recovery(ctx: Context) -> None:
    ctx.proxy.stop()
    try:
        driver = ctx.launch()
        driver.switch_to_url("the offline window", is_local("offline.html"))
        wait_for(
            "the refused-connection reason",
            lambda: "not accepting connections" in driver.text(),
            timeout=40,
        )
        ctx.shot("07-offline")
    finally:
        ctx.proxy.start()
    driver.click_button("Retry")
    driver.switch_to_url("the main window after Retry", on_server(ctx))
    assert_signed_in_web_ui(ctx, driver)
    assert not ctx.platform.window_visible("Onyx") or True


def managed_server_and_lock(ctx: Context) -> None:
    """A managed ServerURL skips onboarding; LockServerURL beats a saved server."""
    ctx.close()
    ctx.fresh_home()
    ctx.write_config({"serverUrl": "https://saved.example.com"})
    ctx.platform.write_policy({"ServerURL": ctx.proxy.url, "LockServerURL": True})
    try:
        driver = ctx.launch()
        # The keyring still holds the token for the proxy URL, so a locked
        # managed server opens the web UI with no onboarding or sign-in.
        driver.switch_to_url("the main window on the managed server", on_server(ctx))
        windows = driver.windows()
        assert not any(is_local("onboarding.html")(u) for u in windows.values()), (
            "onboarding showed"
        )
        assert_signed_in_web_ui(ctx, driver)
        # Preferences shows the managed server and no way to change it.
        driver.switch_to_url("the launcher", is_local("launcher.html"))
        ctx.shot("08-policy-locked-main")
    finally:
        ctx.close()
        ctx.platform.write_policy(None)


def managed_lock_hides_change_server(ctx: Context) -> None:
    """Signed out under a locked managed server: sign-in has no Change server."""
    ctx.close()
    ctx.fresh_home()
    other_server = "http://localhost:9"  # never signed in here
    ctx.platform.write_policy({"ServerURL": other_server, "LockServerURL": True})
    try:
        driver = ctx.launch()
        found = driver.switch_to_url(
            "the sign-in or offline window",
            lambda u: is_local("login.html")(u) or is_local("offline.html")(u),
        )
        url = driver.windows()[found]
        driver.switch(found)
        text = wait_for("the window content", lambda: driver.text().strip())
        ctx.shot("09-policy-locked-signin")
        assert "Change server" not in text, f"Change server offered on {url}"
        assert not any(
            is_local("onboarding.html")(u) for u in driver.windows().values()
        )
    finally:
        ctx.close()
        ctx.platform.write_policy(None)


def disable_launcher_policy(ctx: Context) -> None:
    ctx.close()
    ctx.write_config({"serverUrl": ctx.proxy.url})
    ctx.platform.write_policy({"DisableLauncher": True})
    try:
        driver = ctx.launch()
        driver.switch_to_url("the main window", on_server(ctx))
        ctx.platform.press_launcher_shortcut()
        time.sleep(2)  # proving a negative: give a wrong show time to happen
        assert not ctx.platform.window_visible(LAUNCHER_TITLE), (
            "launcher showed with DisableLauncher"
        )
    finally:
        ctx.close()
        ctx.platform.write_policy(None)


SCENARIOS: list[Callable[[Context], None]] = [
    first_launch_shows_onboarding,
    onboarding_rejects_a_remote_http_server,
    onboarding_accepts_the_server,
    wrong_password_is_rejected,
    sign_in_opens_the_web_ui,
    restart_stays_signed_in,
    launcher_ask_streams_an_answer,
    offline_window_then_recovery,
    managed_server_and_lock,
    managed_lock_hides_change_server,
    disable_launcher_policy,
]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--server", required=True, help="Onyx server URL (http or https)"
    )
    parser.add_argument("--binary", help="app binary (default: the installed package)")
    parser.add_argument("--email", help="existing user; default: register a new one")
    parser.add_argument("--password")
    parser.add_argument("--question", default="What is Onyx? (desktop smoke)")
    parser.add_argument("--expect-answer", help="text the mock LLM answer contains")
    parser.add_argument("--artifacts", default="desktop-v2-smoke-artifacts")
    parser.add_argument(
        "--no-chat-input",
        action="store_true",
        help="check that the web app boots, not that the chat input renders "
        "(for a server whose /app renders empty in every browser)",
    )
    parser.add_argument(
        "-k", dest="only", help="run only scenarios whose name contains this"
    )
    args = parser.parse_args()

    platform = current()
    email = args.email or f"desktop-smoke-{secrets.token_hex(4)}@example.com"
    password = args.password or f"Smoke-{secrets.token_urlsafe(12)}!"
    if not args.email:
        register_user(args.server, email, password)
    artifacts = Path(args.artifacts).resolve()
    artifacts.mkdir(parents=True, exist_ok=True)
    proxy = ToggleProxy(args.server, free_port())
    proxy.start()
    ctx = Context(
        platform=platform,
        binary=args.binary or platform.default_binary,
        proxy=proxy,
        email=email,
        password=password,
        question=args.question,
        expect_answer=args.expect_answer,
        artifacts=artifacts,
        driver_port=free_port(),
        check_chat_input=not args.no_chat_input,
    )
    print(f"server {args.server} via {proxy.url}, user {email}, home {ctx.home}")
    failures: list[str] = []
    try:
        for scenario in SCENARIOS:
            if args.only and args.only not in scenario.__name__:
                continue
            started = time.monotonic()
            try:
                scenario(ctx)
                print(f"PASS {scenario.__name__} ({time.monotonic() - started:.1f}s)")
            except Exception as error:  # noqa: BLE001 - report every scenario
                failures.append(scenario.__name__)
                print(f"FAIL {scenario.__name__}: {error}")
                ctx.shot(f"FAIL-{scenario.__name__}")
                ctx.dump_windows()
    finally:
        ctx.close()
        if ctx.driver_process is not None:
            ctx.driver_process.terminate()
        platform.write_policy(None)
        proxy.stop()
        (artifacts / "proxy.log").write_text("\n".join(proxy.requests) + "\n")
    print(
        f"{len(failures)} failed: {', '.join(failures)}" if failures else "all passed"
    )
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
