# Onyx Mobile — Getting Started (Environment Setup)

One-time setup of the platform tools needed to build Onyx on a Mac. **This doc is setup only** —
once the tools below are installed, see [`README.md`](./README.md) to install deps and run the app.

> macOS only (iOS needs Xcode). **The JDK and NDK are Android-only** — iOS uses neither.

---

## iOS

1. Install **Xcode** from the **Mac App Store**, then open it once so it finishes installing its
   components.
2. **Add a simulator:** Xcode → **Settings → Platforms → iOS Simulator → ＋ Add Additional
   Simulators** to download a runtime, then **Window → Devices and Simulators → Simulators → ＋**
   to create one (the default iPhone is usually fine).
3. RN's iOS build also needs **CocoaPods** — install it if it isn't already (`brew install cocoapods`).

## Android

Android Studio's first run installs the base SDK, and the **build auto-downloads** the rest it
needs (platform, build-tools, CMake) the first time you build. You only install **four things by
hand** — a JDK, Android Studio, the NDK, and an emulator.

**1. JDK 17** — install **Eclipse Temurin 17**:

```bash
brew install --cask temurin@17    # or grab the .pkg installer from https://adoptium.net
```

> **Why Temurin?** It's the standard, free, vendor-neutral OpenJDK 17 build (Eclipse Adoptium) —
> no account or license click-through. But **any JDK 17 distribution is fine** (Zulu, Amazon
> Corretto, Microsoft, or Homebrew's `openjdk@17`) — they're interchangeable; the build only
> cares that it's version **17**.
>
> Why it's a separate step: this is the one piece the build _can't_ fetch for you, and Android
> Studio's bundled JDK is **21** — which the build rejects. So install **17** yourself. (The
> build uses it via `JAVA_HOME`; see [`README.md`](./README.md)'s run steps.)

**2. Android Studio** — download from
**[developer.android.com/studio](https://developer.android.com/studio)** and run the installer.
Open it once and complete the setup wizard (it installs the SDK to `~/Library/Android/sdk`).

**3. NDK — the exact version** — Android Studio → **Settings → Languages & Frameworks → Android
SDK → SDK Tools** tab → tick **"Show Package Details"** (bottom-right) → under **NDK (Side by
side)** check the exact version the build pins, currently **`27.1.12297006`** → **Apply**.

> Use _Show Package Details_ and pick the **exact** version — the plain "NDK (Side by side)"
> checkbox installs the _latest_, which won't satisfy the build. (The required version is printed
> in the build log's `ExpoRootProject → ndk:` line and tracks the Expo SDK.)

**4. Create an emulator (AVD)** — Android Studio **Welcome screen → More Actions → Virtual Device
Manager** (or **View → Tool Windows → Device Manager** inside a project):

1. **Create Device** → pick a recent **Pixel** → **Next**.
2. **System Image** → click the **⬇** next to a recent Android version to download it → select it
   → **Next**.
3. **Verify Configuration → Finish**, then launch it with **▶**.

---

✅ Tools installed. Next → **[`README.md`](./README.md)** to install deps and run the app on the
simulator / emulator.

### Sources

- [Create & manage Android virtual devices](https://developer.android.com/studio/run/managing-avds)
- [Expo — Android Studio emulator](https://docs.expo.dev/workflow/android-studio-emulator/)
- [Apple — install additional Xcode components](https://developer.apple.com/documentation/xcode/downloading-and-installing-additional-xcode-components)
