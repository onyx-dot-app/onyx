# iOS Dev Build — setup notes

The mobile app uses native modules that **do not exist in Expo Go** (`react-native-mmkv`
v4 / Nitro, `@shopify/flash-list`, etc.), so it must be run as a **development build**,
not in Expo Go.

## Hard requirement: no spaces in the project path

React Native / Xcode iOS build scripts (e.g. expo-constants'
`Generate app.config for prebuilt Constants.manifest`) do **not** quote paths, so a space
anywhere in the absolute path breaks the build with a misleading error like:

```
❌ Script '[CP-User] Generate app.config for prebuilt Constants.manifest' failed
   is a directory: /Users/.../Project/Onyx        <-- truncated at the space in "Onyx Folder"
```

The repo was therefore moved out of `.../Project/Onyx Folder/` to a **space-free** path.
Keep it that way.

## Why React Native builds from source here

RN 0.85.x has no published prebuilt RNCore artifact, so CocoaPods fails with
`React-Core-prebuilt ... Missing required attribute 'source'`. Fixed by the
`expo-build-properties` plugin in `app.json`:

```json
["expo-build-properties", { "ios": { "buildReactNativeFromSource": true } }]
```

This flips `RCT_USE_PREBUILT_RNCORE`/`RCT_USE_RN_DEP` off and compiles RN from source
(slower first build, fully reliable).

## Build & run (iOS simulator)

```bash
# Pods/ios bake absolute paths, so regenerate after any move:
rm -rf ios
npx expo prebuild --clean -p ios
# Port 8081 is taken by Docker on this machine; use 8082 (matches package.json "start"):
npx expo run:ios --port 8082
```

First `run:ios` compiles RN from source (~15 min). Subsequent builds are incremental.

If Metro complains about missing modules after a move, run `bun install` first.

## Runtime config

`app.config.ts` reads `ONYX_API_BASE_URL` (and `ONYX_IS_CLOUD`) from the environment for
`appConfig.apiBaseUrl`. Set it so the app can reach the backend, e.g.:

```bash
ONYX_API_BASE_URL=http://<your-mac-LAN-ip>:8080 npx expo run:ios --port 8082
```
