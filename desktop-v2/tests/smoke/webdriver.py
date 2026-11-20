"""A minimal W3C WebDriver client for tauri-driver (stdlib only).

tauri-driver proxies to WebKitWebDriver on Linux and msedgedriver on Windows.
Every Tauri webview window is one WebDriver window handle.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import TypeVar

T = TypeVar("T")

ENTER = "\ue007"
ELEMENT_KEY = "element-6066-11e4-a52e-4f735466cecf"
JsonValue = None | bool | int | float | str | list["JsonValue"] | dict[str, "JsonValue"]


class WebDriverError(RuntimeError):
    pass


def wait_for(description: str, check: Callable[[], T | None], timeout: float = 30) -> T:
    """Polls `check` until it returns a truthy value; WebDriver errors count as not yet."""
    deadline = time.monotonic() + timeout
    last_error = ""
    while time.monotonic() < deadline:
        try:
            value = check()
            if value:
                return value
        except (WebDriverError, OSError) as error:
            last_error = str(error)
        time.sleep(0.3)
    suffix = f" (last error: {last_error})" if last_error else ""
    raise AssertionError(f"timed out waiting for {description}{suffix}")


class WebDriver:
    def __init__(self, base_url: str) -> None:
        self.base_url = base_url
        self.session_id = ""

    def request(
        self, method: str, path: str, payload: JsonValue = None, timeout: float = 60
    ) -> JsonValue:
        data = None if payload is None else json.dumps(payload).encode()
        # Only ever the local tauri-driver URL.
        request = urllib.request.Request(  # noqa: S310
            f"{self.base_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310
                body: dict[str, JsonValue] = json.loads(response.read() or b"{}")
                return body.get("value")
        except urllib.error.HTTPError as error:
            raise WebDriverError(
                f"{method} {path}: {error.read().decode(errors='replace')}"
            ) from error

    def start(self, application: str, args: list[str] | None = None) -> None:
        options: dict[str, JsonValue] = {"application": application}
        if args:
            options["args"] = list(args)
        created = self.request(
            "POST",
            "/session",
            {"capabilities": {"alwaysMatch": {"tauri:options": options}}},
            timeout=120,
        )
        assert isinstance(created, dict)
        session_id = created["sessionId"]
        assert isinstance(session_id, str)
        self.session_id = session_id

    def quit(self) -> None:
        if self.session_id:
            try:
                self.request("DELETE", f"/session/{self.session_id}", timeout=30)
            except (WebDriverError, OSError):
                pass
            self.session_id = ""

    def session(
        self, path: str, method: str = "GET", payload: JsonValue = None
    ) -> JsonValue:
        return self.request(method, f"/session/{self.session_id}{path}", payload)

    def handles(self) -> list[str]:
        value = self.session("/window/handles")
        assert isinstance(value, list)
        return [str(h) for h in value]

    def switch(self, handle: str) -> None:
        self.session("/window", "POST", {"handle": handle})

    def execute(self, script: str, *args: JsonValue) -> JsonValue:
        return self.session(
            "/execute/sync", "POST", {"script": script, "args": list(args)}
        )

    def execute_async(self, script: str, *args: JsonValue) -> JsonValue:
        return self.session(
            "/execute/async", "POST", {"script": script, "args": list(args)}
        )

    def find(self, css: str) -> str:
        element = self.session(
            "/element", "POST", {"using": "css selector", "value": css}
        )
        assert isinstance(element, dict)
        reference = element[ELEMENT_KEY]
        assert isinstance(reference, str)
        return reference

    def type_into(self, css: str, text: str, submit: bool = False) -> None:
        """Real key input, so React's onChange runs as if typed.

        With `submit`, the form submits once the field shows `text`. WebKitWebDriver
        drops a lone Enter after an earlier submit, so a form submits the way
        Enter does (`requestSubmit`); a field outside a form gets Enter.
        """
        element = self.find(css)
        self.session(f"/element/{element}/clear", "POST", {})
        self.session(f"/element/{element}/value", "POST", {"text": text})
        if submit:
            wait_for(
                f"{css} to hold the typed text",
                lambda: self.execute(
                    "return document.querySelector(arguments[0]).value === arguments[1]",
                    css,
                    text,
                ),
                timeout=5,
            )
            submitted = self.execute(
                "const form = document.querySelector(arguments[0]).form;"
                "if (!form) return false; form.requestSubmit(); return true;",
                css,
            )
            if submitted is not True:
                self.session(f"/element/{element}/value", "POST", {"text": ENTER})

    def painted(self) -> None:
        """Waits for two animation frames, so a screenshot shows the latest DOM."""
        # A hidden webview never runs animation frames; the timer ends the wait.
        self.execute_async(
            "const done = arguments[arguments.length - 1];"
            "setTimeout(() => done(false), 500);"
            "requestAnimationFrame(() => requestAnimationFrame(() => done(true)));"
        )

    def click(self, css: str) -> None:
        element = self.find(css)
        self.session(f"/element/{element}/click", "POST", {})

    def click_button(self, label: str) -> None:
        """Clicks the first enabled button whose visible text is `label`."""
        ok = self.execute(
            "const b = [...document.querySelectorAll('button')]"
            ".find(b => b.innerText.trim() === arguments[0] && !b.disabled);"
            "if (!b) return false; b.click(); return true;",
            label,
        )
        if ok is not True:
            raise WebDriverError(f"no enabled button {label!r}")

    def text(self) -> str:
        value = self.execute("return document.body ? document.body.innerText : ''")
        return str(value or "")

    def href(self) -> str:
        return str(self.execute("return location.href") or "")

    def windows(self) -> dict[str, str]:
        """Window handle -> current URL, for every webview. Stays on the current window."""
        try:
            current = str(self.session("/window"))
        except WebDriverError:
            current = ""
        found: dict[str, str] = {}
        for handle in self.handles():
            try:
                self.switch(handle)
                found[handle] = self.href()
            except WebDriverError:
                continue
        if current in found:
            self.switch(current)
        return found

    def switch_to_url(self, description: str, match: Callable[[str], bool]) -> str:
        """Switches to the first window whose URL matches; returns its handle."""

        def find() -> str | None:
            for handle, url in self.windows().items():
                if match(url):
                    self.switch(handle)
                    return handle
            return None

        return wait_for(description, find)
