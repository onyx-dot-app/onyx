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

## CI / release (`.github/workflows/pr-ios-build.yml`)

Mirrors the desktop build flow (`deployment.yml`):

- **PR / merge_group** touching `mobile/**` → `xcodegen generate` + unsigned
  `xcodebuild` simulator build (compile check) + `.app` artifact.
- **Tag `v*.*.*`** (excluding `beta`) → signed device archive + export + **TestFlight
  upload**. Cutting a release tag ships the iOS build.

Signing secrets are pulled from **AWS Secrets Manager** via OIDC — the same mechanism and
the same `deploy/apple-*` secrets the desktop release uses (`APPLE_ID`, `APPLE_PASSWORD`,
`APPLE_CERTIFICATE`, `APPLE_CERTIFICATE_PASSWORD`, `KEYCHAIN_PASSWORD`, `APPLE_TEAM_ID`).
The certificate is imported into a temporary keychain exactly like the desktop job, and the
build is uploaded to TestFlight with `altool` using the existing `APPLE_ID` /
`APPLE_PASSWORD` (app-specific password).

iOS App Store distribution additionally needs a provisioning profile, which macOS Developer
ID signing doesn't — add it to the same secrets store as
**`deploy/apple-ios-provisioning-profile`** (base64 of the `.mobileprovision`) for an
`app.onyx.ios` App Store profile. Build number = the workflow run number.

## Layout

- `project.yml` — XcodeGen spec (bundle id, settings)
- `Sources/OnyxApp.swift` — app entry + `WKWebView` wrapper
