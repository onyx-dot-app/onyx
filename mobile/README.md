# Onyx iOS

Native iOS app for Onyx — a SwiftUI `WKWebView` shell that loads Onyx Cloud
(`https://cloud.onyx.app`) with native loading, pull-to-refresh, and offline error states.

Chosen over Tauri 2 mobile because tauri-cli's iOS build-phase is incompatible with Xcode 26.x
(see the wiki: `engineering/Onyx iOS App/Project Status.md`). This path uses only Swift + a
standard Xcode project, so it builds on current Xcode and signs like any normal iOS app.

## Prerequisites

- Xcode 26.x with an iOS Simulator runtime installed (`xcodebuild -downloadPlatform iOS`)
- `xcodegen` (`brew install xcodegen`) — the `.xcodeproj` is generated, not committed

## Build & run (simulator)

```bash
cd mobile
xcodegen generate
xcodebuild -project Onyx.xcodeproj -scheme Onyx -sdk iphonesimulator \
  -configuration Debug -derivedDataPath build build
xcrun simctl boot "iPhone 17" 2>/dev/null || true
xcrun simctl install booted build/Build/Products/Debug-iphonesimulator/Onyx.app
xcrun simctl launch booted app.onyx.ios
```

## Device / App Store

Set automatic signing with the team in `project.yml` (`DEVELOPMENT_TEAM`), then
`xcodebuild ... -sdk iphoneos -allowProvisioningUpdates`. Bundle id: `app.onyx.ios`.

## Layout

- `project.yml` — XcodeGen spec (bundle id, settings)
- `Sources/OnyxApp.swift` — app entry + `WKWebView` wrapper
