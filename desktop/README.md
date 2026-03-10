# Onyx Desktop

A lightweight macOS desktop application for [Onyx Cloud](https://cloud.onyx.app).

Built with [Tauri](https://tauri.app) for minimal bundle size (~10MB vs Electron's 150MB+).

## Features

- 🪶 **Lightweight** - Native macOS WebKit, no bundled Chromium
- ⌨️ **Keyboard Shortcuts** - Quick navigation and actions
- 🪟 **Native Feel** - macOS-style title bar with traffic lights
- 💾 **Window State** - Remembers size/position between sessions
- 🔗 **Multi-window** - Open multiple Onyx windows

## Keyboard Shortcuts

| Shortcut | Action           |
| -------- | ---------------- |
| `⌘ N`    | New Chat         |
| `⌘ ⇧ N`  | New Window       |
| `⌘ R`    | Reload           |
| `⌘ [`    | Go Back          |
| `⌘ ]`    | Go Forward       |
| `⌘ ,`    | Open Config File |
| `⌘ W`    | Close Window     |
| `⌘ Q`    | Quit             |

## Prerequisites

1. **Rust** (latest stable)

   ```bash
   curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh
   source $HOME/.cargo/env
   ```

2. **Node.js** (18+)

   ```bash
   # Using homebrew
   brew install node

   # Or using nvm
   nvm install 18
   ```

3. **Xcode Command Line Tools**
   ```bash
   xcode-select --install
   ```

## Development

```bash
# Install dependencies
npm install

# Run in development mode
npm run dev

# Run in debug mode
npm run debug
```

## Building

### Build for current architecture

```bash
npm run build
```

### Build Universal Binary (Intel + Apple Silicon)

```bash
# First, add the targets
rustup target add x86_64-apple-darwin
rustup target add aarch64-apple-darwin

# Build universal binary
npm run build:dmg
```

The built `.dmg` will be in `src-tauri/target/release/bundle/dmg/`.

## Project Structure

```
onyx-desktop/
├── package.json          # Node dependencies & scripts
├── src/
│   └── index.html        # Fallback/loading page
└── src-tauri/
    ├── Cargo.toml        # Rust dependencies
    ├── tauri.conf.json   # Tauri configuration
    ├── build.rs          # Build script
    ├── icons/            # App icons
    └── src/
        └── main.rs       # Rust backend code
```

## Icons

Before building, add your app icons to `src-tauri/icons/`:

- `32x32.png`
- `128x128.png`
- `128x128@2x.png`
- `icon.icns` (macOS)
- `icon.ico` (Windows, optional)

You can generate these from a 1024x1024 source image using:

```bash
# Using tauri's icon generator
npm run tauri icon path/to/your-icon.png
```

## Customization

### Self-Hosted / Custom Server URL

The app defaults to `https://cloud.onyx.app` but supports any Onyx instance.

**Config file location:**

- macOS: `~/Library/Application Support/app.onyx.desktop/config.json`
- Linux: `~/.config/app.onyx.desktop/config.json`
- Windows: `%APPDATA%/app.onyx.desktop/config.json`

**To use a self-hosted instance:**

1. Launch the app once (creates default config)
2. Press `⌘ ,` to open the config file, or edit it manually
3. Change the `server_url`:

```json
{
  "server_url": "https://your-onyx-instance.company.com",
  "window_title": "Onyx"
}
```

4. Restart the app

**Quick edit via terminal:**

```bash
# macOS
open -t ~/Library/Application\ Support/app.onyx.desktop/config.json

# Or use any editor
code ~/Library/Application\ Support/app.onyx.desktop/config.json
```

### Change the default URL in build

Edit `src-tauri/tauri.conf.json`:

```json
{
  "app": {
    "windows": [
      {
        "url": "https://your-onyx-instance.com"
      }
    ]
  }
}
```

### Add more shortcuts

Edit `src-tauri/src/main.rs` in the `setup_shortcuts` function.

### Window appearance

Modify the window configuration in `src-tauri/tauri.conf.json`:

- `titleBarStyle`: `"Overlay"` (macOS native) or `"Visible"`
- `decorations`: Window chrome
- `transparent`: For custom backgrounds

## Troubleshooting

### "Unable to resolve host"

Make sure you have an internet connection. The app loads content from `cloud.onyx.app`.

### Build fails on M1/M2 Mac

```bash
# Ensure you have the right target
rustup target add aarch64-apple-darwin
```

### Code signing for distribution

For distributing outside the App Store, you'll need to:

1. Get an Apple Developer certificate
2. Sign the app: `codesign --deep --force --sign "Developer ID" target/release/bundle/macos/Onyx.app`
3. Notarize with Apple

## License

MIT
