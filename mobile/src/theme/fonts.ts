// RN doesn't synthesize weights from one family like web does, so each weight
// loads under its own name. Keep this in sync with the `usedFontFamilies` set
// printed by `bun scripts/generate-theme.ts` — a new preset weight must be added here.

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

// Keyed by the runtime `fontFamily` string the presets reference; registering
// under the google-fonts export name keeps preset values and loaded faces identical.
const FONT_MAP = {
  HankenGrotesk_400Regular,
  HankenGrotesk_500Medium,
  HankenGrotesk_600SemiBold,
  HankenGrotesk_700Bold,
  DMMono_400Regular,
  DMMono_500Medium,
};

// Returns true once all faces are ready; gate rendering on it so text never
// flashes in the system fallback font.
export function useAppFonts(): boolean {
  const [loaded] = useFonts(FONT_MAP);
  return loaded;
}
