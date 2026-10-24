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
    // A lone em dash is the empty-value placeholder in tables and stats, not prose.
    // It is exempt only when it is the whole string or the only JSX child.
    const check = (
      node: ESTree.Node,
      text: string | null | undefined,
      isWholeText: boolean
    ) => {
      if (!text?.includes(EM_DASH)) return;
      if (isWholeText && text.trim() === EM_DASH) return;
      context.report({ node, messageId: "emDash" });
    };
    return {
      Literal(node) {
        if (typeof node.value === "string") check(node, node.value, true);
      },
      TemplateElement(node) {
        const template = node.parent;
        const isWholeText =
          template.type === "TemplateLiteral" &&
          template.expressions.length === 0;
        check(node, node.value.cooked, isWholeText);
      },
      JSXText(node) {
        const isWholeText = node.parent.children.every(
          (child) =>
            child === node ||
            (child.type === "JSXText" && child.value.trim() === "")
        );
        check(node, node.value, isWholeText);
      },
    };
  },
});
