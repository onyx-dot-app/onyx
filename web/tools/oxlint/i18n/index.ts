import { eslintCompatPlugin } from "@oxlint/plugins";

import { noRawJsxTextRule } from "./rules/no-raw-jsx-text.ts";

/**
 * i18n migration ratchet. Rules are "off" by default and enabled per-path via
 * `overrides` in .oxlintrc.json as directories finish their string extraction.
 */
const i18nPlugin = eslintCompatPlugin({
  meta: { name: "i18n" },
  rules: {
    "no-raw-jsx-text": noRawJsxTextRule,
  },
});

export default i18nPlugin;
