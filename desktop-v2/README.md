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

Closing the main window keeps the app running in the menu bar; the Dock icon, the tray's
**Open Onyx** or a second launch brings it back.

## Keyboard shortcuts

| Shortcut | Action |
|---|---|
| `Cmd+N` | New chat |
| `Cmd+,` | Preferences |
| `Cmd+R` | Reload |
| `Ctrl+Cmd+F` | Full screen |
| `Cmd+M`, `Cmd+H`, `Cmd+W`, `Cmd+Q` | Minimize, hide, close window, quit |

## Security boundary

- Only the bundled windows (onboarding, login, preferences)
  can call app commands. Every app command needs an explicit permission (`build.rs` app
  manifest), and the capability in `src-tauri/capabilities/local.json` grants them to those
  windows only. The remote main window gets no app command.
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

Point onboarding at any Onyx server v4.2 or later. The default is `http://localhost:3000`.

## Checks

```bash
bun run typecheck   # tsc
bun run lint:rust   # cargo clippy -D warnings
cargo fmt --manifest-path src-tauri/Cargo.toml --check
cargo test --manifest-path src-tauri/Cargo.toml
```

## Known limits

- wry calls the navigation hook for iframes too, so a cross-origin iframe in the web UI
  opens in the browser instead of rendering inline.
- macOS only for now. The code builds on other platforms, but the launcher panel, native
  cookies and dialogs are macOS-specific.
- The shell-side React and Opal dependencies resolve from `web/node_modules`.
