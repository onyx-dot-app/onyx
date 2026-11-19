# Onyx Desktop v2 (preview)

A native macOS app for Onyx, built with Tauri 2.12. It lives beside `desktop/`, which keeps
shipping unchanged and stays the default desktop app. v2 has its own bundle ID
(`app.onyx.desktop.v2`) and name ("Onyx v2"), so both apps can be installed at the same time.

## What it does

- Native onboarding: enter a server URL. The app checks `GET /api/version`.
- Native sign-in with email and password through `POST /api/auth/mobile/login`. Release builds
  keep the session token in the macOS keychain (service `app.onyx.desktop.v2`, one entry per
  server). Debug builds keep it in `~/Library/Application Support/app.onyx.desktop.v2/
  dev-session-tokens.json` (mode 600): an unsigned dev build gets a new code signature on every
  rebuild, and macOS would ask for your password each time.
- The main window shows the server's own web UI. The shell sets the session cookie in the
  window before the first page load, so the web login page never shows. On macOS the cookie
  is built natively as a host-only, HttpOnly cookie (`src-tauri/src/macos_cookies.rs`):
  wry's `set_cookie` always adds `Domain` and writes `Secure=FALSE`, and WebKit reads any
  `Secure` key as secure, so such a cookie never reaches an `http://` server.
- Link policy, in Rust: same-origin pages stay in the app; other `http(s)`, `mailto:` and
  `tel:` links open in the system browser; other schemes are blocked. Downloads open the
  native save panel. `alert()`, `confirm()` and `prompt()` show native dialogs.
- Tray icon, standard macOS menus (with Edit), and a Preferences window (`Cmd+,`) for the
  server and sign-out.
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
  `POST /api/search/send-search-message` (EE). If Onyx is hidden (`Cmd+H`), the launcher still
  opens over the current app and Onyx stays hidden.
- SSO in the system browser, where you are often signed in already. The browser runs the
  server's normal OAuth flow with Onyx's mobile SSO parameters and PKCE, and the server ends it
  with `onyx://auth/callback?code=..`. The app swaps the one-time code for a session token
  (`src-tauri/src/sso.rs`). The identity provider needs no new redirect URI: the flow returns
  to the web callback that is already registered. It works for the legacy Google sign-in and
  for Google and OIDC providers set up in the admin panel, when the server lists them with
  `native_app_sso`. SAML, cloud workspaces and older servers use the web login page in an app
  window.
- The app renews the session on launch and every 12 hours, so regular use never signs you out.

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

## Keyboard shortcuts

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

## Security boundary

- Only the bundled windows (onboarding, login, preferences, launcher)
  can call app commands. Every app command needs an explicit permission (`build.rs` app
  manifest), and the capability in `src-tauri/capabilities/local.json` grants them to those
  windows only. The remote main window gets no app command.
- The main window gets just two built-in window permissions, on the configured server's origin
  only: start dragging and title-bar zoom (for its drag regions).
- Local windows have a strict CSP (`script-src 'self'`, `connect-src` limited to IPC). The
  Vite plugin adds it as a `<meta>` tag, so it also applies in `bun run dev`; production
  builds also send it as a header (`tauri.conf.json`).
- Local windows never call the server. All HTTP goes through Rust with the bearer token.

## Run it

Prerequisites: Rust 1.90+, Bun 1.3+, Xcode Command Line Tools (full Xcode is not needed),
and a dependency install in `web/` (`desktop-v2` builds Opal from `web/lib/opal/src`).

```bash
cd desktop-v2
bun install
bun run dev
```

Point onboarding at any Onyx server v4.2 or later. The default is `http://localhost:3000`. A remote
server needs `https://`; `http://` works only for a server on this computer.

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
- Run the workflow by hand with a version (for example `0.2.0`) to publish a signed and
  notarized universal DMG, its update archive and `latest.json`. They go to a GitHub
  pre-release tagged `desktop-v2-v<version>`, which is never marked as the latest release, so
  v1's downloads and auto-update are not affected.

## Auto-update

`src-tauri/src/updater.rs`: the app checks the feed 15 seconds after launch
and every 6 hours, downloads a newer version in the background, then changes **Check for
Updates…** (app menu and tray) to **Restart to Update (vX)**. It does not restart on its own.
Every download is verified against `plugins.updater.pubkey` in `tauri.conf.json` before it is
installed; a build that was changed after signing, or signed with another key, is rejected.

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
`toggle_launcher`, `shortcut`, `state`. The harness only acts in debug builds started with
`ONYX_DESKTOP_QA_DIR` set to a private directory (owned by you, mode 0700; created that way if
missing), because it can drive signed-in windows. It cannot press global shortcuts or move the window by drag (both
need the physical mouse or keyboard).

## Known limits

- wry calls the navigation hook for iframes too, so a cross-origin iframe in the web UI
  opens in the browser instead of rendering inline.
- Browser SSO needs a server with the native-app sign-in pass-through in its web OAuth
  callback. v1 also registers the `onyx://` scheme; with both apps installed, macOS sends the
  sign-in link to whichever app registered it last.
- macOS only for now. The code builds on other platforms, but the launcher panel, native
  cookies and dialogs are macOS-specific.
- The shell-side React and Opal dependencies resolve from `web/node_modules`.
