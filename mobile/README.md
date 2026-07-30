# Onyx Mobile (Expo)

A standalone React Native app for Onyx, under `mobile/` — independent of `web/` (its own
dependencies, lockfile, and tooling). Scaffolded with `create-expo-app` (Expo Router template).

## Stack

- **Expo SDK 56** (managed, New Architecture) · **Expo Router** · React 19.2 / RN 0.85 · **Bun**.
- **NativeWind v4** for styling.
  > No design system wired yet — tokens/theme will be imported from the `@onyx-ai/shared`
  > package later (see the `Subash-Mohan/shared-package-mobile-web` branch).
- **TanStack Query** (MMKV-persisted) · **Zustand** · **react-native-mmkv** · **@shopify/flash-list**.

## Prerequisites

> First-time machine setup (Xcode, Android Studio, JDK 17, NDK, simulator/emulator) is in
> [`GETTING_STARTED.md`](./GETTING_STARTED.md). The list below is the short version.

- Node LTS on PATH, **Bun**, Xcode + an iOS simulator, CocoaPods.
- Recommended: `brew install watchman` (faster, more reliable Metro file watching).
- The project path must contain **no spaces** (RN/Xcode build scripts break otherwise).
- Runs as a **development build** (not Expo Go) — `react-native-mmkv` v4 and FlashList are native
  modules absent from Expo Go.

## Setup (from inside `mobile/`)

```bash
bun install
bunx expo install --fix      # reconcile any deps to SDK 56
```

## Run (iOS simulator)

```bash
bun run prebuild -- -p ios   # or: bunx expo prebuild --clean -p ios  (generates ios/)
bun run run:ios              # or: bunx expo run:ios --port 8082
```

> The first iOS build compiles React Native **from source (~15 min)** — RN 0.85 has no prebuilt
> CocoaPods artifact; this is expected, not a hang. Subsequent builds are incremental.
> Metro runs on **port 8082** (8081 is commonly taken by Docker).
>
> **Android** (`bun run run:android`): the build must compile with **JDK 17** — point `JAVA_HOME`
> at one first: `export JAVA_HOME=$(/usr/libexec/java_home -v 17)` (Android Studio's bundled
> JDK 21 won't work). The first Android build compiles native C++ via the NDK (~10–15 min).

## Scripts

| Command                                     | What it does                                              |
| ------------------------------------------- | --------------------------------------------------------- |
| `bun run start` / `ios` / `android` / `web` | Metro / dev menu (port 8082).                             |
| `bun run run:ios` / `run:android`           | Build + launch the native dev build.                      |
| `bun run prebuild`                          | Regenerate the native `ios/` + `android/` projects (CNG). |
| `bun run typecheck`                         | `tsc --noEmit`.                                           |
| `bun run lint`                              | `expo lint` (ESLint flat config + `eslint-config-expo`).  |
| `bun run format` / `format:check`           | Prettier write / check (sorts NativeWind classes).        |

## Project layout

```
src/app/        Expo Router routes (_layout.tsx provider stack, index.tsx placeholder home)
src/query/      TanStack Query client + MMKV persister
src/state/      MMKV instances + storage adapter (shared by Query + zustand persist)
src/global.css  Tailwind entry stylesheet (NativeWind)
```

## Design system

Not wired yet. Tokens, theme, and shared utilities will be imported from the `@onyx-ai/shared`
package once it lands (see the `Subash-Mohan/shared-package-mobile-web` branch). Nothing is
vendored locally — the package owns the Style Dictionary build and the design tokens.

> The splash logo (`assets/images/splash-icon.png`) is a placeholder on the Onyx-blue background
> (`#208AEF`) — replace it with the real Onyx logo art.
