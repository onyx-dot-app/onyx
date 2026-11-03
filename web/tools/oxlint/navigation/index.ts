import { eslintCompatPlugin } from "@oxlint/plugins";

import { noDirectAppNavigationRule } from "./rules/no-direct-app-navigation.ts";

/** Rules that keep in-app navigation going through `AppPosition`. */
const navigationPlugin = eslintCompatPlugin({
  meta: { name: "navigation" },
  rules: {
    "no-direct-app-navigation": noDirectAppNavigationRule,
  },
});

export default navigationPlugin;
