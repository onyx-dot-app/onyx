import { defineRule } from "@oxlint/plugins";

// refresh-components module -> its Opal replacement. Add a row when Opal ships a
// replacement, and delete the row when the refresh module is deleted.
const OPAL_REPLACEMENTS = new Map<string, string>([
  [
    "@/refresh-components/texts/Text",
    "`Text` from `@opal/components` (string-enum `font` and `color` props)",
  ],
  [
    "@/refresh-components/texts/Truncated",
    "`OverflowText` from `@opal/components`",
  ],
  ["@/refresh-components/cards/Card", "`Card` from `@opal/components`"],
  ["@/refresh-components/Divider", "`Divider` from `@opal/components`"],
  [
    "@/refresh-components/buttons/LineItem",
    "`LineItemButton` from `@opal/components`",
  ],
]);

/**
 * Flags imports of refresh-components that Opal replaces. It is a warning so
 * existing callers keep building; the agent edit hook makes agents migrate the
 * file they touch. Read the Opal component's README.md for its props.
 */
export const noReplacedRefreshImportRule = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow refresh-components imports that have an Opal replacement.",
    },
    messages: {
      replaced:
        "`{{source}}` has an Opal replacement: use {{replacement}}. Migrate every use in this file.",
    },
  },
  createOnce(context) {
    return {
      ImportDeclaration(node) {
        const source = node.source.value;
        const replacement = OPAL_REPLACEMENTS.get(source);
        if (replacement === undefined) return;
        context.report({
          node,
          messageId: "replaced",
          data: { source, replacement },
        });
      },
    };
  },
});
