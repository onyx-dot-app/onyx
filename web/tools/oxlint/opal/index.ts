import { eslintCompatPlugin } from "@oxlint/plugins";

import { noLayoutDivRule } from "./rules/no-layout-div.ts";
import { noReplacedRefreshImportRule } from "./rules/no-replaced-refresh-import.ts";
import { noSectionUtilityClassesRule } from "./rules/no-section-utility-classes.ts";

/** Design-system rules that move app code onto Opal. */
const opalPlugin = eslintCompatPlugin({
  meta: { name: "opal" },
  rules: {
    "no-layout-div": noLayoutDivRule,
    "no-replaced-refresh-import": noReplacedRefreshImportRule,
    "no-section-utility-classes": noSectionUtilityClassesRule,
  },
});

export default opalPlugin;
