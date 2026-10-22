import { defineRule, type ESTree } from "@oxlint/plugins";

const EM_DASH = "—";

/** Ban em dashes in strings and JSX text; comments are not copy, so they are not checked. */
export const noEmDashRule = defineRule({
  meta: {
    type: "suggestion",
    docs: {
      description:
        "Disallow em dashes in strings and JSX text that users or agents read.",
    },
    messages: {
      emDash:
        "Do not use em dashes. Use a period, comma, colon, or parentheses instead.",
    },
  },
  createOnce(context) {
    const check = (node: ESTree.Node, text: string | null | undefined) => {
      // A lone em dash is the empty-value placeholder in tables and stats, not prose.
      if (!text?.includes(EM_DASH) || text.trim() === EM_DASH) return;
      context.report({ node, messageId: "emDash" });
    };
    return {
      Literal(node) {
        if (typeof node.value === "string") check(node, node.value);
      },
      TemplateElement(node) {
        check(node, node.value.cooked);
      },
      JSXText(node) {
        check(node, node.value);
      },
    };
  },
});
