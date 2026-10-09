import { defineRule } from "@oxlint/plugins";

// JSX props whose string values render as user-facing copy.
const USER_FACING_PROPS = new Set([
  "label",
  "placeholder",
  "title",
  "description",
  "tooltip",
  "aria-label",
  "alt",
  "emptyMessage",
  "errorMessage",
  "sublabel",
  "subtitle",
]);

// User-facing English copy: contains a word of letters and either starts with
// an uppercase letter or spans multiple words. Skips technical values such as
// "7", "es", "email@yourcompany.com", and single lowercase tokens.
function looksLikeUserFacingCopy(value: string): boolean {
  const trimmed = value.trim();
  if (!/[A-Za-z]{2,}/.test(trimmed)) return false;
  return /^[A-Z]/.test(trimmed) || /\s/.test(trimmed);
}

/**
 * Flags raw English copy in migrated directories: JSX text nodes and
 * user-facing string props must come from the message catalog via
 * `useTranslations`/`getTranslations` instead of string literals.
 *
 * Enabled per-path in .oxlintrc.json `overrides` — the ratchet grows as
 * directories finish their i18n migration and never blocks unmigrated code.
 */
export const noRawJsxTextRule = defineRule({
  meta: {
    type: "problem",
    docs: {
      description:
        "Disallow hardcoded user-facing strings in JSX on i18n-migrated paths; use t() with a key in src/i18n/messages/en.json.",
    },
    messages: {
      rawJsxText:
        "Hardcoded UI text in an i18n-migrated file. Move the string to src/i18n/messages/en.json and render it with t().",
      rawJsxProp:
        'Hardcoded user-facing "{{prop}}" value in an i18n-migrated file. Move the string to src/i18n/messages/en.json and pass t() output.',
    },
  },
  createOnce(context) {
    return {
      JSXText(node) {
        if (looksLikeUserFacingCopy(node.value)) {
          context.report({ node, messageId: "rawJsxText" });
        }
      },
      JSXAttribute(node) {
        if (node.name.type !== "JSXIdentifier") return;
        const propName = node.name.name;
        if (!USER_FACING_PROPS.has(propName)) return;

        // Depending on the AST compat layer, string literals surface as
        // "Literal" or "StringLiteral" — accept both.
        const isStringLiteralNode = (candidate: {
          type: string;
        }): candidate is { type: string; value: unknown } =>
          candidate.type === "Literal" || candidate.type === "StringLiteral";

        const attributeValue = node.value;
        const literal =
          attributeValue !== null && isStringLiteralNode(attributeValue)
            ? attributeValue
            : attributeValue?.type === "JSXExpressionContainer" &&
                isStringLiteralNode(attributeValue.expression)
              ? attributeValue.expression
              : null;

        if (
          literal !== null &&
          typeof literal.value === "string" &&
          looksLikeUserFacingCopy(literal.value)
        ) {
          context.report({
            node: literal,
            messageId: "rawJsxProp",
            data: { prop: propName },
          });
        }
      },
    };
  },
});
