import { existsSync } from "node:fs";
import path from "node:path";

// The redirect URI of preset sign-ins (backend presets.py). Its page must
// render with Craft off, so it cannot sit under the gated /craft layout.
const PRESET_CALLBACK = "/craft/v1/apps/oauth/callback";
const APP_DIR = path.join(__dirname, "../../app");

const hasPage = (route: string): boolean =>
  existsSync(path.join(APP_DIR, route, "page.tsx"));

test("the preset OAuth callback renders outside the Craft layout", async () => {
  const loadConfig = require("../../../next.config.js");
  const config = await loadConfig("phase-production-build", {
    defaultConfig: {},
  });
  const rewrites: { source: string; destination: string }[] =
    await config.rewrites();
  const target =
    rewrites.find((rewrite) => rewrite.source === PRESET_CALLBACK)
      ?.destination ?? PRESET_CALLBACK;

  expect(hasPage(PRESET_CALLBACK)).toBe(false);
  expect(target.startsWith("/craft")).toBe(false);
  expect(hasPage(target)).toBe(true);
});
