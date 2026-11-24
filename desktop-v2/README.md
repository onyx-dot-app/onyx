# Onyx Desktop v2 (preview)

A native desktop app for Onyx, built with Tauri 2.12. macOS is the main platform. Windows and
Linux builds are a preview (see [Windows and Linux](#windows-and-linux)). It lives beside
`desktop/`, which keeps shipping unchanged and stays the default desktop app. v2 has its own bundle ID
(`app.onyx.desktop.v2`) and name ("Onyx v2"), so both apps can be installed at the same time.
On Linux the package name is `onyx-v2` (`src-tauri/tauri.linux.conf.json`), so file names have
no space.

## What it does

- Native onboarding: enter a server URL. The app checks `GET /api/version`.
- Native sign-in with email and password through `POST /api/auth/mobile/login`. Release builds
  keep the session token in the OS credential store (service `app.onyx.desktop.v2`, one entry per
  server): the macOS keychain, Windows Credential Manager, or the Linux Secret Service (GNOME
  Keyring, KWallet). macOS debug builds keep it in `~/Library/Application Support/
  app.onyx.desktop.v2/dev-session-tokens.json` (mode 600): an unsigned dev build gets a new code
  signature on every rebuild, and macOS would ask for your password each time.
  Windows keeps Credential Manager entries after an uninstall. So on Windows the app uses a
  stored token only if its `config.json` records that this install saved it
  (`sessionServers`). If you delete the app's data, or install again after you deleted it, you
  must sign in again. The app then deletes the old token.
- The main window shows the server's own web UI. The shell sets the session cookie in the
  window before the first page load, so the web login page never shows. On macOS the cookie
  is built natively as a host-only, HttpOnly cookie (`src-tauri/src/macos_cookies.rs`):
  wry's `set_cookie` always adds `Domain` and writes `Secure=FALSE`, and WebKit reads any
  `Secure` key as secure, so such a cookie never reaches an `http://` server.
- Link policy, in Rust: same-origin pages and `blob:` URLs stay in the app; other `http(s)`,
  `mailto:` and `tel:` links open in the system browser; other schemes (also `data:`, a
  `blob:` URL from another site, and every `about:` page except `about:blank` and
  `about:srcdoc`) are blocked. Popups and the SSO sign-in window can also load other HTTPS
  sites, for OAuth consent and identity providers. Downloads open the native save panel.
  `alert()`, `confirm()` and `prompt()` show native dialogs.
- Tray icon, standard macOS menus (with Edit), and a Preferences window (`Cmd+,`) for the
  server, the launcher shortcut, **Launch at login** and sign-out.
- Native main window chrome: overlay title bar, the sidebar runs to the top with
  the traffic lights inside it, the collapse button sits on that row, and collapsing slides the
  sidebar fully away. In full screen the button moves to the left edge. The sidebar's top row
  and the chat area's top bar drag the window. Zoom (`Cmd+=`/`Cmd+-`) keeps the title-bar row
  at its native size. Window size and position are remembered.
- Launcher panel on a global shortcut (default `Cmd+Shift+Space`, set in Preferences) that
  works from any app. On macOS it is a non-activating `NSPanel` (`src-tauri/src/launcher.rs`),
  like Spotlight: it appears over the app you are in, also
  full-screen apps and on every Space, without bringing Onyx's other windows forward, and it
  hides when you click away. It keeps its chat and query while hidden, also an answer that is
  still streaming. **Ask** streams an answer through `POST /api/chat/send-chat-message`, shows
  what it is doing (searching, reading sources) until text arrives, and shows the answer as
  markdown. A question after an answer is a follow-up in the same chat. **Search** calls
  `POST /api/search/send-search-message` (EE). When results come from more than one source,
  source chips above them filter the search (`filters.source_type`). If Onyx is hidden
  (`Cmd+H`), the launcher still opens over the current app and Onyx stays hidden.
- Launcher agents: type `@` at the start of the input, or press `Cmd+K`, to pick an agent from
  `GET /api/persona`. As in the web app, built-in agents other than the default one are not
  offered, and the default one is not offered when "Always Start with an Agent" is on. The
  agent shows as a chip; `Backspace` in an empty input removes the last file chip, then the
  agent chip. New chats start with that
  agent, and the choice is saved per server in `config.json`. A follow-up keeps its chat's
  agent; a question for another agent starts a new chat. A server without the agent list uses
  the default agent.
- Launcher attachments: paste or drop files (up to 10) into the launcher. They upload through
  `POST /api/user/projects/file/upload`, as in the web chat, two at a time, and the launcher
  waits until the server has processed them before it sends them with the question. A file
  larger than the server's limit (`GET /api/settings`) or the app's 250 MB limit is rejected
  before it is read. Rejection reasons show on the file's chip. Removing a chip, or `Cmd+N`,
  stops its upload and deletes the file from the user's files (`DELETE
  /api/user/projects/file/{id}`); files sent with a question stay. A file that could not be
  deleted comes back as a failed chip, so removing it again tries again. If a question fails
  before it is sent (for example, the chat could not be created), its files come back.
- A native notification when an Ask answer finishes while the launcher is hidden
  (`src-tauri/src/notify.rs`). The notification does not show the question or the answer,
  because lock screens and notification history keep it. Only the launcher's current answer
  notifies: a new question or a new chat (`Cmd+N`) stops the old answer's notification. A click
  on the notification shows the launcher with the answer. A click does nothing if the launcher
  no longer holds that answer, if you signed out, or if `DisableLauncher` is set. Turn
  notifications off in Preferences, or with the managed `DisableNotifications` bool.
  Click support differs by OS:
  - macOS: a click works while the notification is on screen and from Notification Center.
    In `bun run tauri dev`, macOS shows the notification as Terminal's.
  - Windows: a click works while the toast is on screen and from the Action Center. The toast
    opens an `onyx://launcher/answer` link, which the running app receives (single instance).
  - Linux: a click works only if the notification server supports the `default` action
    (GNOME and KDE do). Otherwise the notification shows, and a click does nothing.
- SSO in the system browser, where you are often signed in already. The browser runs the
  server's normal OAuth flow with Onyx's mobile SSO parameters and PKCE, and the server ends it
  with `onyx://auth/callback?code=..`. The app swaps the one-time code for a session token
  (`src-tauri/src/sso.rs`). The identity provider needs no new redirect URI: the flow returns
  to the web callback that is already registered. It works for the legacy Google sign-in and
  for Google and OIDC providers set up in the admin panel, when the server lists them with
  `native_app_sso`. SAML, cloud workspaces and older servers use the web login page in an app
  window.
- The app renews the session on launch and every 12 hours, so regular use never signs you out.
- Offline window (`src-tauri/src/offline.rs`, `src/pages/Offline.tsx`). If the server cannot
  be reached at launch, or a main-window page does not load and the server then fails two
  health checks (`GET /api/version` for the API and `GET /` for the web UI, every 5 seconds
  for up to a minute while the page has not finished loading), the main window hides and a small window shows "Can't
  reach <host>" with the reason: no network, DNS, TLS certificate, timeout, connection refused
  or a 5xx error. The API check passes only for the Onyx version JSON. Any other answer (a
  network sign-in page, another site) shows "does not look like an Onyx server", and the
  web UI's own `/api` route shows that `/api` does not reach the API server. These reasons,
  and a 5xx error, also replace a page that already loaded. On Linux and Windows, a main-window load
  that the web view cannot finish (for example, connection refused) shows this window instead
  of the web view's error page (on Windows, the main window is blank until then). On Linux and
  Windows, the app also checks the server every 60 seconds while the main window is on screen,
  so an outage while no page loads also shows this window after two failed checks. When the
  server is back, the main window shows that page again without a reload, so unsaved edits stay.
  A certificate error also shows this window, not the web
  view's certificate page, so the user cannot continue to the page. If the app's own check passes but the web view still fails (for
  example, a certificate that only the web view does not trust), the window checks again
  only on **Retry**. Otherwise it checks again after 2, 4, 8, 15, 30, then every 60 seconds, at once when
  the network comes back, and on **Retry**. When the server answers, the main window loads the
  page again, after the server also answers the session check (`GET /api/me`). A session
  check that fails keeps the window and its backoff. A page that already loaded stays when
  the network drops for a short time. Closing the window stops the checks. For a TLS error,
  the window says that a company proxy that inspects secure traffic, or a missing company
  root certificate, is a common cause.
- **Change server** opens onboarding with the current server filled in. The same server keeps
  the session. Another server ends the session, then sign-in opens.
- Sign out, and saving another server, remove the session on this computer at once. If the server
  cannot be reached to end the session, a dialog says so, and the app tries the server
  sign-out again in the background while it runs. The token stays in memory only: it is not
  written back to the keychain, so after a quit the server session ends only when it expires. The launcher, onboarding and sign-in show one line for each of the same errors,
  for example "Can't find <host>. Check the server address." (`src-tauri/src/reachability.rs`).
- If the HTTP client cannot start (for example, a broken OpenSSL configuration), a dialog
  says so and the app quits.

Closing the main window keeps the app running in the menu bar; the Dock icon, the tray's
**Open Onyx** or a second launch brings it back.

### Aonyx (easter egg)

Click the Onyx logo in the launcher five times quickly and Aonyx, the Onyx otter, appears in
the bottom-right corner of the screen (`src-tauri/src/aonyx.rs`, `src/pages/Aonyx.tsx`). It is
a small transparent panel above other apps and on every Space that never takes focus. It
thinks while a launcher answer streams, is happy when it is done, and hops when the launcher
opens. Click it to open the launcher, drag it anywhere, right-click to hide it. Five more logo
clicks send it away. Whether it is shown and where it sits are saved in `config.json`. The
sprite sheets in `public/aonyx/` are played faster than the pack's timing.

## Managed deployment (MDM and Group Policy)

IT can push the app to every device with Kandji, Jamf, Intune or Group Policy, and set it up
in advance. With a managed server, the app skips onboarding and opens at sign-in.

The app reads the policy at launch, every 5 minutes, before each update check, and each time
Preferences opens or comes to the front (`src-tauri/src/policy.rs`). A managed value wins over the user's own
`config.json` value. Preferences shows managed values read-only, with "Managed by your
organization". A `ServerURL` without `LockServerURL` shows "Default set by your organization",
and the user can change it. Sample files for each platform are in [`deploy/`](deploy/).

| Key | Type | Effect |
|---|---|---|
| `ServerURL` | string | The Onyx server. `http://` is allowed here for an intranet server; a server that the user enters must use `https://` (`http://` only for this computer). If the user has not saved a server, onboarding is skipped. A server the user saves later is used instead, unless `LockServerURL` is set. The app keeps only the scheme, host and port: `https://onyx.example.com/app` becomes `https://onyx.example.com`, so Onyx must run at the server root. A URL with a user name or password is not valid. |
| `LockServerURL` | bool | Always use `ServerURL`, and hide **Change server**. Without a valid `ServerURL`, the last valid `ServerURL` is used, else the user's saved server, and the server cannot change. |
| `DisableAutoUpdate` | bool | The updater does not check for updates, and an update that already downloaded is not installed. **Check for Updates…** says that updates are managed. macOS only: Windows and Linux builds do not update themselves, so this key has no effect there. |
| `LauncherShortcut` | string | The launcher shortcut, in the Preferences format, for example `CommandOrControl+Shift+Space`. If another app holds the shortcut, the app tries again at each policy read. |
| `DisableLauncher` | bool | No launcher shortcut, the launcher does not open, **Open Launcher** in the menus is turned off, and Aonyx is hidden. An open launcher and Aonyx close at the next policy read. Aonyx comes back when the launcher turns on again. |
| `LaunchAtLogin` | bool | Turns **Launch at login** on or off, and the Preferences switch is locked. See [Launch at login](#launch-at-login). |
| `DisableNotifications` | bool | Turns off desktop notifications. |

A change to `ServerURL` or `LockServerURL` applies at the next launch. If `LockServerURL` turns
on while the app runs, the server in use is locked until then. If the policy names another
server, Preferences says that Onyx uses it after a restart. The other keys apply at the next
policy read.

Booleans accept `true`/`false`, `1`/`0` and `yes`/`no` (as strings too). Other values are not
valid.

### Invalid policy

The app does not ignore a policy that it cannot read. It fails closed:

- If the policy file or a value cannot be read, Preferences shows "Your organization's Onyx
  policy is invalid. Some settings are locked."
- If the Linux policy file exists but is not a valid JSON object (for example, it has a trailing
  comma), the server is locked and updates are off. A UTF-8 byte order mark is allowed.
- An invalid `LockServerURL` or `Disable*` value counts as `true`.
- An invalid `ServerURL`, `LauncherShortcut` or `LaunchAtLogin` value is ignored. Preferences
  names the ignored setting and does not lock other settings.
- The app remembers the last valid `ServerURL`. If a later policy is invalid and has no valid
  `ServerURL`, the app uses the remembered server, so one bad push does not stop sign-in.
- If the server is locked and no server is known, onboarding shows that the policy is invalid
  and the server field is turned off.

### Launch at login

The app adds a login item for the current user only: a LaunchAgent on macOS,
`HKCU\Software\Microsoft\Windows\CurrentVersion\Run` on Windows, and
`~/.config/autostart/app.onyx.desktop.v2.desktop` on Linux. `LaunchAtLogin` is best effort. A
user can still turn the item off in System Settings, Task Manager or the desktop's startup
settings. While the app runs, it sets the item again within five minutes (at each policy read,
or when Preferences opens). If the app does not run, nothing sets it again. To make sure the
app opens at login, deploy the login item with your management tool instead:

- macOS: a managed login item (the `com.apple.servicemanagement` payload) for the bundle ID
  `app.onyx.desktop.v2`, or a LaunchAgent in `/Library/LaunchAgents`.
- Windows: a value under `HKLM\Software\Microsoft\Windows\CurrentVersion\Run`, with Group
  Policy Preferences or Intune. Quote the path.
- Linux: a `.desktop` file in `/etc/xdg/autostart`.

### macOS

macOS reads forced managed preferences for the bundle ID `app.onyx.desktop.v2`. Values that a
user writes with `defaults write` are not managed and are ignored. Upload this profile
([`deploy/macos/Onyx.mobileconfig`](deploy/macos/Onyx.mobileconfig)) as a
custom configuration profile (Kandji: Custom Profile; Jamf Pro: Configuration Profiles, Upload;
Intune: macOS, Templates, Custom). Give each payload a new `PayloadUUID` (`uuidgen`).

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>PayloadContent</key>
  <array>
    <dict>
      <key>PayloadType</key>
      <string>com.apple.ManagedClient.preferences</string>
      <key>PayloadIdentifier</key>
      <string>com.example.onyx-desktop.preferences</string>
      <key>PayloadUUID</key>
      <string>0B0EFAE4-B391-4C0D-8953-D994C35D8BD8</string>
      <key>PayloadVersion</key>
      <integer>1</integer>
      <key>PayloadDisplayName</key>
      <string>Onyx Desktop settings</string>
      <key>PayloadContent</key>
      <dict>
        <key>app.onyx.desktop.v2</key>
        <dict>
          <key>Forced</key>
          <array>
            <dict>
              <key>mcx_preference_settings</key>
              <dict>
                <key>ServerURL</key>
                <string>https://onyx.example.com</string>
                <key>LockServerURL</key>
                <true/>
                <key>DisableAutoUpdate</key>
                <false/>
                <key>LauncherShortcut</key>
                <string>CommandOrControl+Shift+Space</string>
                <key>DisableLauncher</key>
                <false/>
                <key>LaunchAtLogin</key>
                <true/>
                <key>DisableNotifications</key>
                <false/>
              </dict>
            </dict>
          </array>
        </dict>
      </dict>
    </dict>
  </array>
  <key>PayloadType</key>
  <string>Configuration</string>
  <key>PayloadIdentifier</key>
  <string>com.example.onyx-desktop</string>
  <key>PayloadUUID</key>
  <string>B9F776F8-59CA-4093-9C03-95707C6E65EA</string>
  <key>PayloadVersion</key>
  <integer>1</integer>
  <key>PayloadDisplayName</key>
  <string>Onyx Desktop</string>
  <key>PayloadScope</key>
  <string>System</string>
</dict>
</plist>
```

To see what the app gets on a device, run `defaults read "/Library/Managed Preferences/app.onyx.desktop.v2"`.

### Windows

The app reads `HKLM\SOFTWARE\Policies\Onyx\Desktop`, then the same key under `HKCU`. A machine
value wins over a user value. If the app cannot read a machine key or value (for example, access
is denied), it does not use the user value. The value is not valid. Use `REG_SZ` for strings and `REG_DWORD` (`0` or `1`) for booleans.
For Group Policy or Intune (imported ADMX), use the templates in
[`deploy/windows/`](deploy/windows/): copy `Onyx.admx` to `PolicyDefinitions` and `en-US/Onyx.adml`
to `PolicyDefinitions/en-US`. You can also deploy the values with Group Policy Preferences
(Registry), an Intune script, or this file:

```reg
Windows Registry Editor Version 5.00

[HKEY_LOCAL_MACHINE\SOFTWARE\Policies\Onyx\Desktop]
"ServerURL"="https://onyx.example.com"
"LockServerURL"=dword:00000001
"DisableAutoUpdate"=dword:00000000
"LauncherShortcut"="CommandOrControl+Shift+Space"
"DisableLauncher"=dword:00000000
"LaunchAtLogin"=dword:00000001
"DisableNotifications"=dword:00000000
```

The installer does not set policy values yet (no `msiexec ... SERVER_URL=` property). Deploy them
separately.

### Linux

The app reads `/etc/onyx-desktop/policy.json`, one JSON object with the same keys
([`deploy/linux/policy.json`](deploy/linux/policy.json)). Make it readable by all users, and
writable only by root (for example, `root:root` with mode `644`). The app does not trust the file
if it, or a directory above it, is not owned by root or is writable by group or others. A sticky
directory such as `/tmp` is allowed. Each symlink on the path must also be owned by root, and the
directories on the way to its target get the same check. A file that is not trusted counts as a policy that cannot be read (see
[Invalid policy](#invalid-policy)).

```json
{
  "ServerURL": "https://onyx.example.com",
  "LockServerURL": true,
  "DisableAutoUpdate": false,
  "LauncherShortcut": "CommandOrControl+Shift+Space",
  "DisableLauncher": false,
  "LaunchAtLogin": true,
  "DisableNotifications": false
}
```

## Keyboard shortcuts

On macOS. For Windows and Linux, see [Windows and Linux](#windows-and-linux).

| Shortcut | Action |
|---|---|
| `Cmd+Shift+Space` (global, configurable) | Show or hide the launcher |
| `Cmd+N` | New chat |
| `Cmd+,` | Preferences |
| `Cmd+R` | Reload |
| `Cmd+[` / `Cmd+]` | Back / forward |
| `Cmd+0` / `Cmd+=` / `Cmd+-` | Actual size / zoom in / zoom out (remembered) |
| `Ctrl+Cmd+F` | Full screen |
| `Cmd+M`, `Cmd+H`, `Cmd+W`, `Cmd+Q` | Minimize, hide, close window, quit |
| Launcher: `Enter`, `Tab`, `Cmd+Enter`, `Esc` | Ask or search, switch mode, open in window, close |
| Launcher: `Cmd+N`, `↑` in an empty input | New chat, recent questions |
| Launcher: `@` at the start, `Cmd+K` | Pick an agent (`↑`/`↓`, `Enter`) |
| Launcher: `Cmd+C` (no text selected), `Cmd+Shift+C` | Copy the answer, or the focused source's link |
| Launcher: `Cmd+1`–`9`, `Cmd+Shift+1`–`9` | Open source `[n]` (or search result n), copy its link |

## Security boundary

- Only the bundled windows (onboarding, login, preferences, launcher, aonyx, offline)
  can call app commands. Every app command needs an explicit permission (`build.rs` app
  manifest). Each window has its own capability in `src-tauri/capabilities/` (file name =
  window label) that grants only the commands its page uses. The remote main window gets no
  app command.
- The notification plugin is registered without its JavaScript (`notify::plugin`), so no
  webview, the remote main window included, gets the plugin's `window.Notification` script.
  Only Rust shows notifications, and no window has a notification permission.
- The main window gets just two built-in window permissions, on the configured server's origin
  only: start dragging and title-bar zoom (for its drag regions).
- Local windows have a strict CSP (`script-src 'self'`, `connect-src` limited to IPC). The
  Vite plugin adds it as a `<meta>` tag, so it also applies in `bun run dev`; production
  builds also send it as a header (`tauri.conf.json`).
- Local windows never call the server. All HTTP goes through Rust with the bearer token. The
  Rust client follows a redirect only on the server's origin (scheme, host and port), so a
  password or an SSO code never goes to another host or over plain HTTP.

## Run it

Prerequisites: Rust 1.90+, Bun 1.3+, and a dependency install in `web/` (`desktop-v2` builds
Opal from `web/lib/opal/src`). Also, per platform:

- macOS: Xcode Command Line Tools (full Xcode is not needed).
- Windows: Microsoft C++ Build Tools ("Desktop development with C++") and the WebView2 runtime
  (included in Windows 10 and 11).
- Linux (Debian or Ubuntu):

  ```bash
  sudo apt-get install build-essential file libayatana-appindicator3-dev libdbus-1-dev \
    libgtk-3-dev librsvg2-dev libssl-dev libwebkit2gtk-4.1-dev libxdo-dev patchelf pkg-config
  ```

```bash
cd desktop-v2
bun install
bun run dev
```

Point onboarding at any Onyx server v4.2 or later. The default is `http://localhost:3000`. A remote
server needs `https://`; `http://` works only for a server on this computer: `localhost`, a
loopback IP address, or on macOS also a `*.localhost` name. Windows and Linux can send
`*.localhost` names to DNS, so they need `https://` for them.

## Checks

```bash
bun run typecheck   # tsc
bun run vite:build  # the Rust build embeds dist/, so build it first
bun run lint:rust   # cargo clippy -D warnings
cargo fmt --manifest-path src-tauri/Cargo.toml --check
cargo test --manifest-path src-tauri/Cargo.toml
```

## Builds and releases

`.github/workflows/desktop-v2.yml`:

- On pull requests that touch `desktop-v2/`, CI runs the checks and builds an unsigned
  universal (Apple silicon and Intel) DMG as a workflow artifact for reviewers. macOS blocks
  an unsigned app on first launch: right-click it, choose **Open**, then **Open** again.
- The same pull requests also run the checks on Windows and Linux, and build unsigned x64
  installers as artifacts: NSIS (`.exe`) and MSI on Windows, AppImage and `.deb` on Linux.
  These installers are not signed. They are for review only, not for customers. Their version
  has the workflow run number as build metadata (for example `0.1.0+454`), so the About dialog,
  the package and the installed programs list tell builds apart. Each one has
  a GitHub build provenance attestation (`gh attestation verify <file> --repo
  onyx-dot-app/onyx`). Pull requests from forks get no installer artifacts.
- Run the workflow by hand on `main` with a version (for example `0.2.0`) to publish a signed
  and notarized universal DMG, its update archive and `latest.json`. They go to a GitHub
  pre-release tagged `desktop-v2-v<version>`, which is never marked as the latest release, so
  v1's downloads and auto-update are not affected. Releases are macOS only for now. The job
  gets the signing secrets only after the JavaScript build, and only in its signing step.

### Windows code signing

The Windows installers and the app are not Authenticode-signed yet, so SmartScreen shows
"Unknown publisher". The Windows build step in `desktop-v2.yml` has a hook for it: when the
repository variable `DESKTOP_V2_WINDOWS_SIGN_COMMAND` is set, the build passes it to Tauri as
`bundle.windows.signCommand`. Tauri then runs the command for each file it signs (the app, the
NSIS uninstaller, the NSIS installer and the MSI) and puts the file path in place of `%1`. Tauri
splits the command at spaces, so a path in it cannot contain a space. A later step then fails
the build if one of the installers, or the app inside the MSI or the NSIS installer, has no
valid signature. Tauri restores the unsigned app in `target/release` after it packages each
installer, so that copy is not checked.

Release engineering must supply:

- A code-signing certificate for the publisher name. New OV and EV certificates keep the key
  in a hardware module, so a `.pfx` file in a secret is not an option. A cloud signing
  service, for example Azure Artifact Signing, works with `signCommand`.
- The sign command, for example
  `trusted-signing-cli -e <endpoint> -a <account> -c <profile> -d "Onyx" %1`, and the tool
  it calls, installed in the job.
- The credentials for that command. Prefer short-lived OIDC credentials (the job already has
  `id-token: write`) over a stored secret.
- A decision about where to sign. Today the hook is in the pull request job, which runs branch
  code. To sign only releases, add a Windows job to the protected `release` environment and
  move the hook there.
- The publisher name. `tauri.windows.conf.json` sets `bundle.publisher` to `Onyx`. Make it
  agree with the certificate's subject name.

## Windows and Linux

To build installers locally (unsigned, in `src-tauri/target/release/bundle/`):

```bash
bun run tauri build --bundles nsis,msi      # Windows
bun run tauri build --bundles appimage,deb  # Linux
```

How the app differs from macOS:

- The launcher shortcut is `Ctrl+Alt+Space` by default (`Ctrl+Shift+Space` often switches the
  input language). The launcher is a borderless, always-on-top window with no taskbar entry. It
  opens in the center of the monitor under the pointer. It takes focus when it shows (on X11
  it asks the window manager with a fresh X timestamp) and hides when you click away or press
  `Esc`. In the launcher, `Ctrl+Enter` opens the chat in the window and `Ctrl+N` starts a new
  chat.
- On Linux, Aonyx leaves always-on-top while a file chooser of the main window is open, so it
  does not cover the chooser's buttons.
- On Linux, the context menu of a link to the server has no **Open Link in New Window**: that
  window would have no menu bar. **Open Link** opens it in the same window.
- The main window keeps the native title bar and has its own menu bar: **File** (New Chat
  `Ctrl+N`, Open Launcher, Preferences `Ctrl+,`, Close Window `Ctrl+W`, Quit `Ctrl+Q`), **View**
  (Reload `Ctrl+R`, Back `Alt+Left`, Forward `Alt+Right`, zoom `Ctrl+0`/`Ctrl+=`/`Ctrl+-`, Full
  Screen `F11`) and **Help** (About). Other windows have no menu bar. On Windows the shortcuts
  also work while the page has focus: the app reads them from WebView2's accelerator key event.
- On Windows a left click on the tray icon opens Onyx and a right click opens the tray menu.
- Downloads on Linux do not open a save dialog: WebKitGTK asks on the GTK main thread, where a
  blocking dialog would deadlock. The file goes to the Downloads folder (a name that is already
  in use gets a number). A notification then names the file and its folder; click it to show
  the file in its folder. A failed download also shows a notification.
- On Linux the main window lets the page write the clipboard after a request finishes (for
  example **Create Share Link**). Reading the clipboard still needs a paste. The text context
  menu shows WebKit's standard items only.
- No auto-update: the update feed has macOS builds only, so the app does not check for updates
  and has no **Check for Updates…** item. Install a new version by hand.
- The session cookie goes in through wry's cookie API. Its domain has no leading dot, so
  WebView2 and WebKitGTK keep it host-only, as macOS does. WebView2 and WebKitGTK show
  `alert()`, `confirm()` and `prompt()` themselves; other native dialogs use `rfd`.
- On Linux the web views keep cookies in memory only (`src-tauri/src/linux_cookies.rs`), so
  the session cookie that the server sets is not written to disk outside the Secret Service.
  The app hands the session to the main window each time it opens the window. Other cookies of
  the web UI (for example the sidebar state) reset when the app quits. Local storage stays on
  disk. At launch the app deletes the `cookies` file that older builds wrote to
  `~/.local/share/app.onyx.desktop.v2/`.
- The web sign-in window (SAML, cloud workspaces, older servers) is titled "Onyx web sign-in"
  and sends the web view's own user agent. On macOS it sends Safari's, because Google refuses
  WKWebView's default one. The native sign-in window hides while the web sign-in window is open, and
  shows again when you close that window or the sign-in fails.
- Windows installers install for all users (NSIS `perMachine`, and MSI) into Program Files, so
  a standard user cannot replace the app's files. They need administrator rights. They contain the
  WebView2 offline installer, so they also work on a computer with no internet access. The
  installers register `onyx://` sign-in links for all users. Debug builds register them for
  the current user at launch.
- Installer rules (`src-tauri/windows/`):
  - The NSIS installer (`.exe`) stops when the user is not an administrator. A silent install
    (`/S`) then exits with code 740.
  - Use one installer type on a computer. When the MSI version is installed, the NSIS
    installer stops before its first page (a silent install exits with code 1638). The MSI
    stops when the NSIS version is installed. Uninstall the other one first.
  - Both installers refuse to install an older version over a newer one. Uninstall the newer
    version first.
  - The NSIS uninstaller option **Delete the application data** also deletes the session
    tokens from the user's Credential Manager. It does this only when the uninstaller runs as
    the signed-in Windows user, not when another administrator's credentials elevate it. A
    plain uninstall keeps the app's data and the token.
  - An MSI uninstall keeps the app's data and the token. To also delete the data of the
    user who runs `msiexec`, set `DELETEAPPDATA=1`:
    `msiexec /x {ProductCode} DELETEAPPDATA=1`. This deletes that user's
    `%APPDATA%\app.onyx.desktop.v2` and `%LOCALAPPDATA%\app.onyx.desktop.v2` after the
    uninstall succeeds. It does not go into junctions or symbolic links: it keeps the links
    inside these folders, and when a folder is itself a link it removes only the link. Link
    targets do not change. An upgrade never deletes data.
  - An uninstall that runs as LocalSystem (SCCM, Intune) deletes no user data, also with
    `DELETEAPPDATA=1`: each user controls their own folders, so a delete as LocalSystem is not
    safe there. After such an uninstall, each user's data folders and session token stay
    (the token in that user's Credential Manager). The `DELETEAPPDATA=1` uninstall also keeps
    the token in Credential Manager. The app uses a stored token only when the user's
    config records it, so the user must sign in again when the config is gone or the user
    signed out. The app then deletes the old token. If the config is still there, a reinstall
    uses the token.
- On Linux the `.deb` registers `onyx://` in its desktop file (`onyx-v2.desktop`). AppImage
  and other builds that do not run from `/usr/bin` register it for the current user at launch,
  so they get sign-in links too. This needs `xdg-mime`. At each launch, a `.deb` install makes
  `onyx-v2.desktop` the current user's default for `onyx://` (v1 can also claim the scheme),
  and removes the per-user `onyx://` entry that earlier versions wrote. This cleanup happens
  per user, at that user's first launch of the new version, not at package install. After
  `apt remove`, the default names a desktop file that no longer exists, and the desktop ignores
  it. The AppImage entry points to the AppImage's path at its last launch. If you move or rename the AppImage, quit the app, then
  launch it once from its new path. A launch while the app runs only shows the running app.
- Linux builds need glibc 2.35 or newer (Ubuntu 22.04, Debian 12 and later). CI builds them on
  Ubuntu 22.04 and fails if a file in the `.deb` or the AppImage needs a newer glibc.

Linux needs some desktop services:

- **Secret Service**, to keep you signed in: GNOME Keyring, KWallet or another provider must
  run and be unlocked in your session. Minimal window managers, VDI and SSH sessions often have
  none. Then sign-in fails with a message that names the problem: no provider, no default
  keyring, no D-Bus session bus, or a locked keyring. If the keyring is locked at launch, Onyx
  asks to unlock it one time. If you cancel, Onyx says that it could not read the session and
  offers **Try Again** and **Sign In**.
- **Answer notifications** need a notification server and a session bus that the app can find
  through `DBUS_SESSION_BUS_ADDRESS` or `$XDG_RUNTIME_DIR/bus`. A bus that only X11 autolaunch
  finds is not enough; the app then logs a warning and shows no notification.
- **HiDPI**: GTK reads the scale from `GDK_SCALE` and `GDK_DPI_SCALE`, not from the KDE
  display settings. On a KDE X11 session at 200% with neither set, the windows show at 1x and
  look small. Start the app with `GDK_SCALE=2`.
- **Global shortcut**: the launcher shortcut uses X11 key grabs. In a Wayland session (the
  default on Ubuntu 22.04+, Fedora and RHEL 9) the shortcut works only while an X11 (XWayland)
  app has focus, and with no XWayland it never works. Preferences shows a notice then. Open the
  launcher from the tray icon instead. Preferences also shows a notice when another app holds
  the shortcut.
- **Tray icon**: it needs a tray host (`libayatana-appindicator3-1`). Stock GNOME shows no
  tray icon without the AppIndicator extension (`gnome-shell-extension-appindicator`, on by
  default on Ubuntu). The icon file goes to `$XDG_RUNTIME_DIR/tray-icon`. When that directory
  is not set or the app cannot write to it (for example after `su`, or in some SSH and VDI
  sessions), it goes to `~/.cache/app.onyx.desktop.v2/tray-icon`. If the tray icon still
  fails, the app logs the error and runs without it. Launch the app again to show its window.
- The launcher's transparent corners need a compositing window manager. Without one, the
  corners show black. With no compositor and software rendering, WebKitGTK can also leave a
  stale rectangle on screen until the next repaint.
- The title bar and the menu bar follow the desktop theme, not the color mode of the web UI.

## Auto-update

macOS only (`updater::SUPPORTED`). `src-tauri/src/updater.rs`: the app checks the feed 15 seconds after launch
and every 6 hours, downloads a newer version in the background, then changes **Check for
Updates…** (app menu and tray) to **Restart to Update (vX)**. It does not restart on its own.
Every download is verified against `plugins.updater.pubkey` in `tauri.conf.json` before it is
installed; a build that was changed after signing, or signed with another key, is rejected.
The plugin installs only a version newer than the running one. `requireSignedVersion` makes it
also check the version in the signature, so a changed feed cannot offer an old signed build
under a new version number.
The managed `DisableAutoUpdate` key turns off all checks.

- The feed (`plugins.updater.endpoints`) must be HTTPS. It points at a feed that does not exist
  yet, so checks fail quietly until the feed is set up.
- The public key in `tauri.conf.json` is a development key. Before the first release, create
  the release key pair, put the public key here and the private key in CI's secrets. If that
  private key is lost, installed apps can never update again.

To test an update end to end on one Mac, make a key pair with `bun run tauri signer generate`,
then build an old and a new version with a config overlay that points the feed at a local
server and allows plain HTTP for that test only:

```bash
echo '{"version":"0.1.0","bundle":{"createUpdaterArtifacts":true},"plugins":{"updater":{"pubkey":"<public key>","endpoints":["http://127.0.0.1:8765/latest.json"],"dangerousInsecureTransportProtocol":true}}}' > /tmp/old.json
sed 's/0.1.0/0.1.1/' /tmp/old.json > /tmp/new.json
export TAURI_SIGNING_PRIVATE_KEY="$(cat <private key file>)" TAURI_SIGNING_PRIVATE_KEY_PASSWORD=""
bun run tauri build --debug --bundles app --config /tmp/old.json   # copy the .app somewhere, run it
bun run tauri build --debug --bundles app --config /tmp/new.json   # serve the .app.tar.gz + latest.json
```

`latest.json` lists the version and, per platform (`darwin-aarch64`, `darwin-x86_64`), the
archive URL and the contents of its `.sig` file.

## QA harness (debug builds)

`src-tauri/src/qa.rs` drives the running app with real AppKit key and mouse events posted to
its own event queue, so shortcuts go through the menus and the web view as if typed. Write a
JSON action such as `{"op":"key","key":"n","mods":["cmd"]}` to a temporary file in
`$ONYX_DESKTOP_QA_DIR` and rename it to `<name>.json` when complete; the answer
appears, complete, in `<name>.out.json`. Other ops:
`windows`, `focus`, `bounds`, `eval`, `type`, `click`, `dblclick`, `drag`, `menu`,
`toggle_launcher`, `shortcut`, `state`, and `pasteboard`: `{"op":"pasteboard","image":"<png>"}`
(or `"file"` or `"text"`) puts content on the clipboard for a `Cmd+V` test, and
`{"op":"pasteboard"}` reads its text back after a copy. The harness only acts in debug builds started with
`ONYX_DESKTOP_QA_DIR` set to a private directory (owned by you, mode 0700; created that way if
missing), because it can drive signed-in windows. It cannot press global shortcuts or move the window by drag (both
need the physical mouse or keyboard).

## Logs

The app writes its log to `onyx.log` in the app's log folder (`init_logging` in
`src-tauri/src/main.rs`, with `tauri-plugin-log`):

| OS | Folder |
|---|---|
| macOS | `~/Library/Logs/app.onyx.desktop.v2/` |
| Windows | `%LOCALAPPDATA%\app.onyx.desktop.v2\logs\` |
| Linux | `~/.local/share/app.onyx.desktop.v2/logs/` (`$XDG_DATA_HOME` if set) |

Times are UTC. The log records the app's own messages at level `info` and higher: the app
version and OS at startup, the saved server, sign-in (password or SSO) and sign-out, sign-in
failures, offline and recovery, managed policy errors, downloads and failed links. At 1 MB the
file rotates to `onyx_<date>.log`, and the app keeps the four newest of those files. The log
never holds a password, session token, cookie or sign-in code; URLs are written without their
user info, query and fragment (`main_window::log_safe`). Debug builds also write the log to
stderr. If the folder cannot be written, the app runs without a log.

## Known limits

- wry calls the navigation hook for iframes too, so a cross-origin iframe in the web UI
  opens in the browser instead of rendering inline.
- Tauri does not give the app the HTTP status or load error of a main-window page. The
  offline window uses the health checks only. If one page fails while `GET /api/version`
  and `GET /` answer, the main window keeps that failed page.
- Browser SSO needs a server with the native-app sign-in pass-through in its web OAuth
  callback. v1 also registers the `onyx://` scheme; with both apps installed, macOS sends the
  sign-in link to whichever app registered it last.
- Windows and Linux are a preview: no signed builds, no auto-update feed, and no QA harness
  input (it posts AppKit events). Aonyx is a plain always-on-top window there, so clicking it
  can take focus from the app you are in.
- On Windows, if the launcher opens while another app holds the foreground lock, Windows can
  refuse it focus. Click the launcher once to type.
- The shell-side React and Opal dependencies resolve from `web/node_modules`.
- Proxies: the main window uses the OS WebView and follows every OS proxy setting. The
  app's own requests (health check, sign-in, launcher) use `reqwest`, which reads
  `HTTPS_PROXY`, `HTTP_PROXY`, `ALL_PROXY` and `NO_PROXY`, and the fixed HTTP and HTTPS
  proxies in macOS network settings and the Windows Internet Options. It does not read PAC
  files or WPAD, or the Linux desktop proxy settings. Behind such a proxy the offline window
  can show while the server is reachable; set `HTTPS_PROXY` for the app as a workaround.
