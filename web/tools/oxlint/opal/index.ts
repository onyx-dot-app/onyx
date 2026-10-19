import { eslintCompatPlugin } from "@oxlint/plugins";

import { noReplacedRefreshImportRule } from "./rules/no-replaced-refresh-import.ts";

/** Design-system rules that move app code onto Opal. */
const opalPlugin = eslintCompatPlugin({
  meta: { name: "opal" },
  rules: {
    "no-replaced-refresh-import": noReplacedRefreshImportRule,
  },
});

export default opalPlugin;
