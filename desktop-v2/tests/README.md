# Desktop v2 regression tests

Two checks run outside the Rust unit tests (`cargo test`):

| Check | What it catches | Where it runs |
| --- | --- | --- |
| `contract/check_web_contract.py` | The shell and the server or web app disagree on a route, the cookie name, the sign-in deep link or the hand-off page | Source part: every PR that touches `desktop-v2/`, `web/src/app/auth/`, `web/src/lib/auth/` or `backend/onyx/server/auth/`. Live part: with the smoke test |
| `smoke/run.py` | A built installer that does not work: launch, onboarding, sign-in, main window, launcher Ask, managed policy, offline | Linux now (`run-linux.sh`). Windows and macOS: see the plans below |

## Contract check

```bash
# Source only. No server, no build, about 1 second.
python3 desktop-v2/tests/contract/check_web_contract.py
# Also the live response shapes that the shell parses.
python3 desktop-v2/tests/contract/check_web_contract.py --server http://localhost:3000
```

The source part reads the constants on each side and compares them: the default
cookie name (`api.rs` and `backend/onyx/configs/constants.py`), the `onyx://auth/callback`
deep link (`sso.rs`, `web/src/lib/auth/appHandoff.ts` and the backend allowlist), the
`/auth/app-handoff` page, and the backend routes that the shell calls. The live part
registers a user and checks `/api/version`, `/api/auth/type`, `/api/auth/mobile/login`
(good and bad password), `/api/me` with the token as a bearer and as the session cookie,
`/api/auth/mobile/refresh`, `/api/auth/mobile/logout` and the hand-off page.

## Runtime smoke test (Linux)

The test drives the installed app through `tauri-driver` and `WebKitWebDriver`. It runs in a
throwaway X server (Xvfb), D-Bus session and GNOME Keyring, so it does not touch your desktop
session or your keyring.

```bash
sudo apt-get install -y ./Onyx_v2_*_amd64.deb \
  webkit2gtk-driver xvfb xdotool imagemagick gnome-keyring libsecret-tools dbus-x11 openbox
cargo install tauri-driver --locked
desktop-v2/tests/smoke/run-linux.sh --server https://onyx.example.com
# One scenario (substring match): -k launcher. Another build: --binary path/to/onyx-desktop-v2
```

- The server must allow password sign-up, or give `--email` and `--password`.
- The app connects through a local proxy (`smoke/proxy.py`) on `http://127.0.0.1:<port>`.
  The test stops the proxy to make "the server" go down. This also covers a self-hosted
  server on plain HTTP, which the app allows only on loopback.
- The managed-policy scenarios write `/etc/onyx-desktop/policy.json` with `sudo` and put the
  original file back at the end.
- Screenshots and `tauri-driver.log` go to `--artifacts` (default `desktop-v2-smoke-artifacts/`).
- The sign-in scenarios wait for the web UI's chat input. Against a server whose `/app` renders
  empty in every browser (for example a `next dev` server behind a Cloudflare quick tunnel),
  give `--no-chat-input`: the test then checks that the web app boots and `/api/me` works.
- With `--expect-answer TEXT`, the launcher scenario checks the mock LLM's fixed answer.
  Use the mock LLM server in `backend/tests/integration/mock_services/mock_llm_server/`.

Scenarios, in order (each launch reuses the same profile, so sign-in must survive restarts):

1. First launch shows onboarding.
2. Onboarding rejects `http://` for a remote host.
3. Onboarding accepts `  http://127.0.0.1:<port>/ ` (spaces and the trailing slash are removed)
   and saves the server.
4. A wrong password shows an error and stays on sign-in.
5. Sign-in opens the web UI on `/app`, `/api/me` is the test user, the token is in the keyring.
6. A restart opens the web UI with no sign-in.
7. `Ctrl+Alt+Space` opens the launcher; an Ask streams an answer; Esc hides the launcher.
8. With the server down, the offline window shows the reason; Retry opens the web UI when the
   server is back.
9. Policy `ServerURL` + `LockServerURL` wins over a saved server and skips onboarding.
10. A locked managed server that the user has not signed in to: no "Change server", no onboarding.
11. Policy `DisableLauncher`: the shortcut does not open the launcher.

### How it works

- `smoke/webdriver.py`: a small W3C WebDriver client (standard library only). Each Tauri
  webview is a window handle; the test finds a window by its URL.
- `smoke/platforms.py`: what WebDriver cannot do, per OS: write policy, read the credential
  store, press the global shortcut, see native windows, take a full-screen screenshot.
- WebKitWebDriver drops a lone Enter after an earlier form submit. `type_into(..., submit=True)`
  submits a form with `requestSubmit()` (what Enter does) after React shows the typed text.

## Plan: Windows

Same `run.py`, a `Windows` class in `platforms.py`, on `windows-latest`:

- Driver: `tauri-driver` proxies to `msedgedriver`. Install the driver that matches the
  runner's WebView2 runtime (`msedgedriver-tool` or the version in
  `HKLM\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}`).
- Install: run the NSIS installer silently (`/S`) and the MSI with `msiexec /i ... /qn` in
  separate jobs, so both installers are tested. Uninstall at the end and check that the
  `onyx://` handler and Start menu entry are gone.
- Policy: `reg add "HKLM\SOFTWARE\Policies\Onyx\Desktop" /v ServerURL /t REG_SZ /d ...`
  and `/v LockServerURL /t REG_DWORD /d 1`. Test HKCU too and check that HKLM wins.
  Import `deploy/windows/Onyx.admx` with `LGPO.exe` in one job to test the template itself.
- Credential store: read the token with the `CredRead` API (PowerShell `CredentialManager`
  module or `ctypes`).
- Shortcut and windows: `SendInput` through `ctypes` for `Ctrl+Alt+Space`; `EnumWindows` and
  `IsWindowVisible` for the launcher; `PIL.ImageGrab` for screenshots. The runner has an
  interactive desktop session, so no virtual display is needed.

## Plan: macOS

WKWebView has no WebDriver, so `tauri-driver` does not work on macOS. Use the QA harness
(`src-tauri/src/qa.rs`, debug builds with `ONYX_DESKTOP_QA_DIR`) as the macOS backend:

- Add a `Mac` class in `platforms.py` that writes the harness's JSON commands (navigate,
  evaluate script, type, click, screenshot) and reads the results, with the same interface as
  `WebDriver`. Then the scenarios in `run.py` run on all three systems.
- Policy: `defaults write /Library/Managed\ Preferences/app.onyx.desktop.v2 ServerURL ...`
  (needs sudo on the runner) or install `deploy/macos/Onyx.mobileconfig` in a profile test.
- Credential store: `security find-generic-password -s app.onyx.desktop.v2`.
- Shortcut: the harness already sends AppKit key events; global shortcut tests need
  Accessibility permission, which hosted runners do not give. Run those on a self-hosted Mac.
- The release DMG is signed and notarized; test it once per release with `spctl -a` and a
  manual launch, because the QA harness exists only in debug builds.

## Proposed CI

| Job | Runner | Trigger | Takes |
| --- | --- | --- | --- |
| Contract (source) | ubuntu-latest | PRs that touch the paths above | < 1 min |
| Smoke, Linux `.deb` | ubuntu-24.04 | PRs to `desktop-v2/`, nightly | ~10 min after the build |
| Smoke, Linux AppImage | ubuntu-24.04 | Nightly (`APPIMAGE_EXTRACT_AND_RUN=1`) | ~10 min |
| Smoke, Windows NSIS and MSI | windows-latest | Nightly, release | ~15 min |
| Smoke, macOS (QA harness, debug build) | macos-latest | Nightly | ~15 min |
| Contract (live) | each smoke job | With the smoke test | < 1 min |

Each smoke job downloads the installer artifact from `check-and-build-*` in
`.github/workflows/desktop-v2.yml`, starts a server, installs the build and runs `run.py`.
For the server, use the same stack that the Playwright job uses, with the mock LLM server as
the default LLM provider, so the launcher answer is fixed and `--expect-answer` can check it.
Upload `desktop-v2-smoke-artifacts/` on failure.

### Workflow matrix (all platforms)

| Area | Checks | Linux | Windows | macOS |
| --- | --- | --- | --- | --- |
| Auth | onboarding validation, password sign-in, wrong password, restart keeps session, sign out, SSO hand-off (`onyx://` callback) | smoke | smoke | harness |
| Launcher | shortcut opens, Ask streams, Esc hides, `DisableLauncher`, custom `LauncherShortcut` | smoke | smoke | harness, shortcut on self-hosted |
| Offline | server down at launch, Retry, server down after sign-in, Change server | smoke | smoke | harness |
| Policy | `ServerURL`, `LockServerURL`, `DisableLauncher`, `LauncherShortcut`, `DisableAutoUpdate`, `LaunchAtLogin`, `DisableNotifications`, policy change while running | JSON file | HKLM, HKCU, ADMX | managed prefs, profile |
| Install/upgrade | install, upgrade from previous release keeps sign-in and config, uninstall cleans up | `.deb`, AppImage | NSIS, MSI | DMG (manual) |
| Deep links | `onyx://` registered after install, opens the running app, single instance | `xdg-mime` | registry | Launch Services |
| Notifications | answer-ready notification, `DisableNotifications` | D-Bus `org.freedesktop.Notifications` monitor | toast (manual) | manual |
