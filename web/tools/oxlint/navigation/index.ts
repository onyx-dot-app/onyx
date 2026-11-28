import { eslintCompatPlugin } from "@oxlint/plugins";

import { noNakedNavigationRule } from "./rules/no-naked-navigation.ts";

/** Rules that keep every navigation going through `@opal/navigation`. */
const navigationPlugin = eslintCompatPlugin({
  meta: { name: "navigation" },
  rules: {
    "no-naked-navigation": noNakedNavigationRule,
  },
});

export default navigationPlugin;
