# Onyx Mobile

Cross-platform Onyx mobile app built with **Capacitor** — one codebase for **iOS +
Android**. The native shell wraps the Onyx web UI; the goal is to point it at a mobile-first
build of `web/` (Opal components, matched to the Figma mocks). For now it loads
`https://cloud.onyx.app` directly (`server.url` in `capacitor.config.json`).

App id: `app.onyx.mobile` (iOS bundle id + Android package).

## Prerequisites

- Node + [bun](https://bun.sh) (repo standard)
- iOS: Xcode 26.x + an iOS Simulator runtime (`xcodebuild -downloadPlatform iOS`)
- Android: Android Studio / Android SDK + JDK 21

## Setup

The native projects (`ios/`, `android/`) are **generated, not committed** — recreate them:

```bash
cd mobile
bun install
bunx cap add ios
bunx cap add android
bunx cap sync
```

## Build & run (iOS simulator)

```bash
xcodebuild -project ios/App/App.xcodeproj -scheme App -sdk iphonesimulator \
  -configuration Debug -derivedDataPath build CODE_SIGNING_ALLOWED=NO build
xcrun simctl install booted build/Build/Products/Debug-iphonesimulator/App.app
xcrun simctl launch booted app.onyx.mobile
# or, interactively: bunx cap run ios
```

Android: `bunx cap run android` (or open `android/` in Android Studio).

## Notes

- **Google SSO**: `capacitor.config.json` sets a mobile Safari/Chrome `overrideUserAgent` so
  Google's "Use secure browsers" check doesn't block OAuth in the web view.
- Capacitor 8 uses **Swift Package Manager** for iOS (no CocoaPods).
- Native UX (push, haptics, status bar, keyboard, safe areas) is added via Capacitor plugins
  as the mobile UI is built out.

## Layout

- `capacitor.config.json` — app id, name, `server.url`, per-platform UA overrides
- `www/` — placeholder web dir (replaced by the mobile Opal build)
- `resources/icon.png` — 1024px app icon source (for `@capacitor/assets`)
