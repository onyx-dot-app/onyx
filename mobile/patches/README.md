# Patches

Applied via bun's `patchedDependencies` (see `package.json`); bun re-applies them on every `bun install`.

Both keys name an **exact** version. If the package drifts off that version, bun applies **nothing and
prints no warning**, so `package.json` `overrides` pins each patched package to the version its patch was
cut for. Bump the override, the `patchedDependencies` key, and the patch filename together.

## `metro@0.84.5.patch` — Bundle Mode `.worklets` SHA-1 fix

This is **Software Mansion's official react-native-worklets Bundle Mode patch**, copied verbatim for our
metro version (only the diff paths are rewritten from patch-package's `node_modules/metro/...` to bun's
package-relative `src/...`; the resulting metro blob hash matches SWM's, so the patched file is identical).

- Source: <https://github.com/software-mansion/react-native-reanimated/tree/main/packages/react-native-worklets/bundleMode/patches/patch-package/metro>
- Setup docs: <https://docs.swmansion.com/react-native-worklets/docs/bundleMode/setup/>

**Why it's needed.** `react-native-streamdown` uses worklets **Bundle Mode**, which compiles each worklet
into its own module file under `node_modules/react-native-worklets/.worklets/*.js` **on the fly — after**
metro's one-time startup file crawl. Those files are never in metro's file map, so
`DependencyGraph.getOrComputeSha1` throws `Failed to get the SHA-1 for: …/.worklets/*.js` ([metro#330](https://github.com/facebook/metro/issues/330)).
The patch short-circuits `getOrComputeSha1` for `.worklets` paths and returns a synthetic hash instead of
throwing. SWM calls this "a temporary workaround until necessary changes are merged into Metro" — no metro
release through 0.85.0 fixes it.

Metro reaches us through `@expo/metro`, which is a re-export shim (`module.exports = require("metro/...")`),
so patching the bare `metro` package is what takes effect. `@expo/metro` itself contains no metro source.

**On a metro version bump** (e.g. an Expo SDK upgrade): grab the matching `metro+<version>.patch` from the
SWM link above, re-cut it for the new version (`bun patch metro` → apply the change → `bun patch --commit`),
and re-check [metro#330](https://github.com/facebook/metro/issues/330) — if it's fixed in the metro your SDK
pulls, drop this patch entirely. `src/node-haste/DependencyGraph.js` was byte-identical from 0.84.4 to
0.84.5, so that re-cut needed no content change.
