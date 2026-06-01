/**
 * fonts.ts — Opal typeface loading for the mobile app.
 *
 * The generated typography presets (src/theme/generated/typography.ts) point
 * `fontFamily` at WEIGHT-SPECIFIC loaded faces, e.g. "HankenGrotesk_600SemiBold"
 * and "DMMono_400Regular". React Native does not synthesize weights from a
 * single family the way the web does, so each weight must be loaded under its
 * own name. This module loads exactly the weight objects those presets
 * reference — no more, no less (keeping the bundle lean and avoiding orphan
 * family names).
 *
 * Keep the registered map below in sync with the `usedFontFamilies` set printed
 * by `bun scripts/generate-theme.ts`. If a new preset introduces a new weight,
 * the generator's report will list it and you must add the matching weight
 * object here.
 */

import { useFonts } from "expo-font";

import {
  HankenGrotesk_400Regular,
  HankenGrotesk_500Medium,
  HankenGrotesk_600SemiBold,
  HankenGrotesk_700Bold,
} from "@expo-google-fonts/hanken-grotesk";
import {
  DMMono_400Regular,
  DMMono_500Medium,
} from "@expo-google-fonts/dm-mono";

/**
 * The font map passed to `useFonts`. Each KEY is the runtime `fontFamily`
 * string that the generated typography presets reference; each VALUE is the
 * bundled .ttf module from @expo-google-fonts. Registering under the
 * google-fonts export name keeps preset `fontFamily` values and loaded faces
 * identical (no aliasing, no drift).
 */
const FONT_MAP = {
  HankenGrotesk_400Regular,
  HankenGrotesk_500Medium,
  HankenGrotesk_600SemiBold,
  HankenGrotesk_700Bold,
  DMMono_400Regular,
  DMMono_500Medium,
};

/**
 * Load the Opal typefaces (Hanken Grotesk + DM Mono) at exactly the weights the
 * typography presets use. Returns `true` once all faces are ready.
 *
 * Wire this into the app root and gate rendering on the returned boolean so text
 * never flashes in the system fallback font.
 */
export function useAppFonts(): boolean {
  const [loaded] = useFonts(FONT_MAP);
  return loaded;
}
