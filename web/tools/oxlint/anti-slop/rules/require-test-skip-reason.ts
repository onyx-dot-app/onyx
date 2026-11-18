import { defineRule, type ESTree } from "@oxlint/plugins";

import { disabledTests, testBindings } from "../shared/test-framework.ts";
import { callPath, isFunction, staticText } from "../shared/test-syntax.ts";

const issueUrl =
  /https:\/\/(?:github\.com\/[\w.-]+\/[\w.-]+\/issues\/\d+|linear\.app\/[\w-]+\/issue\/[\w-]+)(?=[/\s)]|$)/u;

function hasReason(node: ESTree.Node | undefined): boolean {
  return Boolean(
    staticText(node)?.trim() ||
    (node?.type === "TemplateLiteral" &&
      node.quasis.some((part) => part.value.cooked?.trim()))
  );
}

export const requireTestSkipReasonRule = defineRule({
  meta: {
    type: "problem",
    docs: { description: "Require a reason to skip a test." },
    messages: {
      reason: "Explain the condition in the second argument to test.skip.",
      issue:
        "Add a Skip: comment directly above the disabled test with a reason and a GitHub or Linear issue URL.",
    },
  },
  create(context) {
    const bindings = testBindings(context.filename);
    return {
      ImportDeclaration: bindings.ImportDeclaration,
      VariableDeclarator: bindings.VariableDeclarator,
      CallExpression(node) {
        const parts = callPath(node.callee);
        const [root] = parts;
        const method = parts.at(-1);
        if (
          bindings.playwright &&
          !parts.includes("skip") &&
          !parts.includes("fixme")
        )
          return;
        const test = root ? bindings.testName(root) : undefined;
        if (
          !test ||
          (!disabledTests.has(test) &&
            !parts.includes("skip") &&
            !parts.includes("fixme"))
        )
          return;
        if (
          node.parent.type === "CallExpression" &&
          node.parent.callee === node
        )
          return;

        const [condition, reason] = node.arguments;
        const conditional =
          bindings.playwright &&
          method === "skip" &&
          !parts.includes("describe") &&
          condition &&
          condition.type !== "TemplateLiteral" &&
          !(
            condition.type === "Literal" &&
            (condition.value === true || typeof condition.value === "string")
          ) &&
          !isFunction(reason);
        if (conditional) {
          if (!hasReason(reason)) context.report({ node, messageId: "reason" });
          return;
        }

        let statement: ESTree.Node = node;
        while (
          statement.parent &&
          !/(?:Statement|Declaration)$/u.test(statement.type)
        ) {
          statement = statement.parent;
        }
        const comment = context.sourceCode.getCommentsBefore(statement).at(-1);
        const note = comment?.value.trim().match(/^Skip:\s*(.+)$/u)?.[1];
        if (
          note &&
          comment?.loc.end.line === statement.loc.start.line - 1 &&
          issueUrl.test(note) &&
          /\w/u.test(note.replace(issueUrl, ""))
        )
          return;

        context.report({ node, messageId: "issue" });
      },
    };
  },
});
